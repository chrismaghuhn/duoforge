#include "eval/graph.h"
#include "eval/kernels.h"
#include "state/context_internal.h"
#include "support/check.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>

#ifdef DF_EVAL_ALLOC_HOOKS
static bool allocation_watch;
static uint64_t allocations;
void *__real_malloc(size_t n);
void *__real_calloc(size_t n, size_t s);
void *__real_realloc(void *p, size_t n);
void __real_free(void *p);
void *__wrap_malloc(size_t n);
void *__wrap_calloc(size_t n, size_t s);
void *__wrap_realloc(void *p, size_t n);
void __wrap_free(void *p);
void *__wrap_malloc(size_t n) { if(allocation_watch)++allocations;return __real_malloc(n); }
void *__wrap_calloc(size_t n,size_t s) { if(allocation_watch)++allocations;return __real_calloc(n,s); }
void *__wrap_realloc(void *p,size_t n) { if(allocation_watch)++allocations;return __real_realloc(p,n); }
void __wrap_free(void *p) { if(allocation_watch)++allocations;__real_free(p); }
#endif
static FILE *open_file(const char *path, const char *mode)
{
#if defined(_MSC_VER)
    FILE *file = NULL;
    return fopen_s(&file,path,mode) == 0 ? file : NULL;
#else
    return fopen(path,mode);
#endif
}
static uint32_t read32(FILE *f, bool *ok)
{
    uint8_t b[4];
    if (fread(b,1u,4u,f) != 4u) { *ok=false;return 0u; }
    return (uint32_t)b[0] | (uint32_t)b[1]<<8u | (uint32_t)b[2]<<16u | (uint32_t)b[3]<<24u;
}
static bool put32(FILE *f, uint32_t value)
{
    uint8_t b[4];
    for(uint32_t i=0u;i<4u;++i)b[i]=(uint8_t)(value>>(8u*i));
    return fwrite(b,1u,4u,f)==4u;
}
typedef struct trace_output { FILE *file; uint32_t row; } trace_output;
static duoforge_status trace_write(void *user,const char *name,uint32_t index,
    uint32_t type,const void *data,uint32_t count)
{
    trace_output *out=user;
    const uint32_t n=(uint32_t)strlen(name);
    if(!put32(out->file,out->row)||!put32(out->file,index)||!put32(out->file,count)||!put32(out->file,n)||
       fwrite(name,1u,n,out->file)!=n)return DUOFORGE_E_INVARIANT;
    for(uint32_t i=0u;i<count;++i) {
        int32_t value=0;
        if(type==1u)value=((const int16_t *)data)[i];
        else if(type==2u)value=((const int32_t *)data)[i];
        else if(type==3u)value=(int32_t)((const uint32_t *)data)[i];
        else if(type==4u)value=((const uint8_t *)data)[i];
        else return DUOFORGE_E_INVARIANT;
        if(!put32(out->file,(uint32_t)value))return DUOFORGE_E_INVARIANT;
    }
    return DUOFORGE_OK;
}
static duoforge_status refuse_trace(void *user,const char *name,uint32_t index,
    uint32_t type,const void *data,uint32_t count)
{
    (void)user;(void)index;(void)type;(void)data;(void)count;
    return strcmp(name,"value")==0 ? DUOFORGE_E_INVARIANT : DUOFORGE_OK;
}
static bool all_bytes(const uint8_t *data,size_t n,uint8_t expected)
{
    for(size_t i=0u;i<n;++i)if(data[i]!=expected)return false;
    return true;
}
static uint64_t get64(const uint8_t *p)
{
    uint64_t value=0u;for(uint32_t i=0u;i<8u;++i)value|=(uint64_t)p[i]<<(8u*i);return value;
}
static int64_t signed64(uint64_t x) { return x<=INT64_MAX?(int64_t)x:-1-(int64_t)(UINT64_MAX-x); }
static int wide_vectors(const char *source,const char *dest)
{
    FILE *input=open_file(source,"rb"),*output=open_file(dest,"wb");
    if(input==NULL||output==NULL) {
        if(input!=NULL)(void)fclose(input);
        if(output!=NULL)(void)fclose(output);
        return 2;
    }
    int failed=0;uint8_t frame[64];size_t n;
    while((n=fread(frame,1u,sizeof frame,input))!=0u) {
        if(n!=sizeof frame){failed=1;break;}
        uint64_t a[8];for(uint32_t i=0u;i<8u;++i)a[i]=get64(frame+8u*i);
        int64_t value=0;duoforge_status st=DUOFORGE_E_INVALID_ARGUMENT;
        if(a[0]==0u) {
            uint64_t bound=0u;
            st=dfi_eval_dot_bound32((uint32_t)a[1],(uint32_t)a[2],(uint32_t)a[3],a[4],
                (dfi_eval_scale){(uint32_t)a[5],(uint32_t)a[6]},&bound);
            if(st==DUOFORGE_OK)value=(int64_t)bound;
        }else if(a[0]==1u) {
            int32_t in[2]={(int32_t)signed64(a[1]),(int32_t)signed64(a[2])},out=0;
            int8_t w[2]={(int8_t)signed64(a[3]),(int8_t)signed64(a[4])};
            int64_t bias=signed64(a[5]);dfi_eval_scale scale={(uint32_t)a[6],(uint32_t)a[7]};
            st=dfi_eval_dense_i32(in,2u,w,&bias,&scale,1u,false,&out);
            if(st==DUOFORGE_OK)value=out;
        }
        if(!put32(output,(uint32_t)st)||!put32(output,(uint32_t)(uint64_t)value)||
           !put32(output,(uint32_t)((uint64_t)value>>32u))){failed=1;break;}
    }
    if(ferror(input))failed=1;
    if(fclose(input)!=0)failed=1;
    if(fclose(output)!=0)failed=1;
    return failed?2:0;
}
typedef struct cold_allocations { size_t count,frees,fail; } cold_allocations;
static void *cold_allocate(size_t bytes,void *user)
{
    cold_allocations *a=user;
    if(a->count++==a->fail)return NULL;
    return calloc(1u,bytes);
}
static void cold_release(void *p,void *user)
{
    cold_allocations *a=user;if(p!=NULL)++a->frees;free(p);
}
static void units(df_test *t)
{
    const uint32_t ids[]={1001u,1002u,1003u};
    const uint32_t parameters[]={1802441u,333769u,773193u};
    for(size_t i=0u;i<3u;++i) {
        const dfi_eval_shape *s=dfi_eval_shape_lookup(ids[i]);
        if(!DF_CHECK(t,s!=NULL))continue;
        DF_CHECK_EQ_U64(t,s->parameters,parameters[i]);
        DF_CHECK(t,dfi_eval_graph_scratch(s)>0u&&dfi_eval_graph_scratch(s)<=s->graph->scratch_per_worker);
        DF_CHECK_EQ_U64(t,s->graph->scratch_max,32u*s->graph->scratch_per_worker);
        DF_CHECK_EQ_U64(t,s->graph->max_leaves,65536u);
        DF_CHECK_EQ_U64(t,s->graph->tensor_count,16u+4u*s->layers);
    }
    DF_CHECK(t,dfi_eval_shape_lookup(0u)==NULL&&dfi_eval_shape_lookup(1u)==NULL&&dfi_eval_shape_lookup(1004u)==NULL);
    int32_t in[2]={INT32_MIN,INT32_MAX},out[2]={77,77};
    int8_t weights[4]={1,0,0,1};int64_t bias[2]={0,0};dfi_eval_scale scales[2]={{1,0},{1,0}};
    DF_CHECK_EQ_U64(t,dfi_eval_dense_i32(in,2u,weights,bias,scales,2u,false,out),DUOFORGE_OK);
    DF_CHECK(t,out[0]==INT32_MIN&&out[1]==INT32_MAX);
    scales[0].shift=1u;scales[1].shift=1u;
    DF_CHECK_EQ_U64(t,dfi_eval_dense_i32(in,2u,weights,bias,scales,2u,false,out),DUOFORGE_OK);
    DF_CHECK(t,out[0]==-1073741824&&out[1]==1073741824);
    bias[0]=INT64_MAX;
    DF_CHECK_EQ_U64(t,dfi_eval_dense_i32(in,2u,weights,bias,scales,2u,false,out),DUOFORGE_E_EXHAUSTED);
    DF_CHECK_EQ_U64(t,dfi_eval_dense_i32(NULL,2u,weights,bias,scales,2u,false,out),DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK_EQ_U64(t,dfi_eval_dense_i32(in,0u,weights,bias,scales,2u,false,out),DUOFORGE_E_INVALID_ARGUMENT);
    uint64_t bound=77u;
    DF_CHECK_EQ_U64(t,dfi_eval_dot_bound32(UINT32_MAX,UINT32_C(2147483648),128u,0u,(dfi_eval_scale){1,0},&bound),DUOFORGE_E_EXHAUSTED);
    DF_CHECK_EQ_U64(t,bound,77u);
    DF_CHECK_EQ_U64(t,dfi_eval_dot_bound32(2u,UINT32_C(2147483648),128u,0u,(dfi_eval_scale){1,0},&bound),DUOFORGE_OK);
    DF_CHECK_EQ_U64(t,bound,UINT64_C(549755813888));
    DF_CHECK_EQ_U64(t,dfi_eval_dot_bound32(1u,UINT32_MAX,1u,0u,(dfi_eval_scale){1,0},&bound),DUOFORGE_E_INVALID_ARGUMENT);
}
static void run_graph(df_test *t,const duoforge_context *ctx,duoforge_evaluator *model,
    const char *bits_path,const char *trace_path)
{
    FILE *input=open_file(bits_path,"rb"),*output=open_file(trace_path,"wb");
    if(!DF_CHECK(t,input!=NULL&&output!=NULL)) {
        if(input!=NULL)(void)fclose(input);
        if(output!=NULL)(void)fclose(output);
        return;
    }
    bool ok=true;const uint32_t count=read32(input,&ok);
    if(!DF_CHECK(t,ok&&count>0u&&count<=16u)){(void)fclose(input);(void)fclose(output);return;}
    duoforge_eval_workspace *w=NULL;
    duoforge_eval_error error;
    DF_CHECK_EQ_U64(t,duoforge_eval_workspace_create(model,65537u,1u,&w,&error),DUOFORGE_E_CAPACITY);
    DF_CHECK_EQ_U64(t,duoforge_eval_workspace_create(model,32u,33u,&w,&error),DUOFORGE_E_CAPACITY);
    duoforge_eval_workspace *maximum=NULL;
    if(DF_CHECK_EQ_U64(t,duoforge_eval_workspace_create(model,65536u,32u,&maximum,&error),DUOFORGE_OK)) {
        DF_CHECK_EQ_U64(t,maximum->scratch_bytes,model->graph->scratch_max);
        DF_CHECK_EQ_U64(t,duoforge_eval_workspace_destroy(maximum,&error),DUOFORGE_OK);
    }
    if(!DF_CHECK_EQ_U64(t,duoforge_eval_workspace_create(model,32u,1u,&w,&error),DUOFORGE_OK)) {
        (void)fclose(input);(void)fclose(output);return;
    }
    (void)ctx;
    DF_CHECK_EQ_U64(t,dfi_eval_workspace_acquire(w,model,model->context,count,1u,&error),DUOFORGE_OK);
    uint32_t bits[1094],first[1094];int32_t first_value=0;
    const dfi_eval_shape *shape=dfi_eval_shape_lookup(model->graph->id);
    const size_t required=dfi_eval_graph_scratch(shape);
    const size_t cold_bytes=model->file_bytes+model->parameter_bytes+sizeof *model+sizeof *model->lifetime;
    DF_CHECK(t,(uint64_t)cold_bytes<=2u*model->graph->file_max+65536u);
    printf("graph_resources %u scratch=%zu decoded=%zu cold=%zu\n",model->graph->id,required,model->parameter_bytes,cold_bytes);
    bool first_ready=false;
    for(uint32_t row=0u;row<count;++row) {
        for(uint32_t j=0u;j<1094u;++j)bits[j]=read32(input,&ok);
        if(!DF_CHECK(t,ok))break;
        memset(w->scratch,0xA5,w->scratch_bytes);
        int32_t value=77;
        DF_CHECK_EQ_U64(t,dfi_eval_graph_row(model,w->scratch,required-1u,0u,bits,NULL,&value,&error),DUOFORGE_E_CAPACITY);
        DF_CHECK_EQ_U64(t,value,77u);
        DF_CHECK(t,all_bytes(w->scratch,w->scratch_bytes,0xA5));
        DF_CHECK_EQ_U64(t,dfi_eval_graph_row(model,w->scratch,w->scratch_bytes,16u,bits,NULL,&value,&error),DUOFORGE_E_CAPACITY);
        trace_output destination={output,row};const dfi_eval_trace trace={trace_write,&destination};
        const duoforge_status status=dfi_eval_graph_row(model,w->scratch,w->scratch_bytes,(row*7u)%16u,bits,&trace,&value,&error);
        if(status!=DUOFORGE_OK)fprintf(stderr,"graph refused: %u %s\n",(uint32_t)status,error.reason);
        if(!DF_CHECK_EQ_U64(t,status,DUOFORGE_OK))break;
        if(row==0u){memcpy(first,bits,sizeof first);first_value=value;first_ready=true;}
        const int32_t expected=value;
        memset(w->scratch,0x5A,w->scratch_bytes);
#ifdef DF_EVAL_ALLOC_HOOKS
        allocations=0u;allocation_watch=true;
#endif
        const duoforge_status warmed=dfi_eval_graph_row(model,w->scratch,w->scratch_bytes,15u,bits,NULL,&value,&error);
#ifdef DF_EVAL_ALLOC_HOOKS
        allocation_watch=false;DF_CHECK_EQ_U64(t,allocations,0u);
#endif
        DF_CHECK_EQ_U64(t,warmed,DUOFORGE_OK);DF_CHECK(t,value==expected);
        const dfi_eval_trace late={refuse_trace,NULL};value=77;
        DF_CHECK_EQ_U64(t,dfi_eval_graph_row(model,w->scratch,w->scratch_bytes,0u,bits,&late,&value,&error),DUOFORGE_E_INVARIANT);
        DF_CHECK(t,value==77&&strcmp(error.reason,"eval_trace_refused")==0);
    }
    DF_CHECK(t,fgetc(input)==EOF);
    if(first_ready) {
        int32_t again=0;
        DF_CHECK_EQ_U64(t,dfi_eval_graph_row(model,w->scratch,w->scratch_bytes,1u,first,NULL,&again,&error),DUOFORGE_OK);
        DF_CHECK(t,again==first_value);
        const size_t low=(size_t)(uintptr_t)w->scratch&127u;
        uint8_t *aligned=w->scratch+((128u-low)&127u);
        memcpy(aligned+4376u,first,sizeof first);
        const uint32_t *reserved=(const uint32_t *)(const void *)(aligned+4376u);
        DF_CHECK_EQ_U64(t,dfi_eval_graph_row(model,w->scratch,w->scratch_bytes,1u,reserved,NULL,&again,&error),DUOFORGE_OK);
        DF_CHECK(t,again==first_value);
        DF_CHECK_BYTES(t,aligned+4376u,(const uint8_t *)first,sizeof first,"reserved input row remains intact");
        const dfi_eval_column *columns=dfi_eval_input_columns();
        for(uint32_t j=0u;j<1094u;++j)if(columns[j].group==DFI_EVAL_GROUP_SPECIES) {
            first[j]=UINT32_C(0x3f800000);again=77;
            DF_CHECK_EQ_U64(t,dfi_eval_graph_row(model,w->scratch,w->scratch_bytes,1u,first,NULL,&again,&error),DUOFORGE_E_UNSUPPORTED);
            DF_CHECK(t,again==77&&strstr(error.reason,columns[j].name)!=NULL);break;
        }
    }
    DF_CHECK(t,fclose(input)==0);
    DF_CHECK(t,fclose(output)==0);
    dfi_eval_workspace_release(w);
    DF_CHECK_EQ_U64(t,duoforge_eval_workspace_destroy(w,&error),DUOFORGE_OK);
}
int main(int argc,char **argv)
{
    const duoforge_context_config config={DUOFORGE_DATA_KIND_CLOSURE,6u,4u,0u,0u,NULL};
    duoforge_context *context=NULL;
    if(duoforge_context_create(&config,&context)!=DUOFORGE_OK)return 2;
    if(argc==4&&strcmp(argv[1],"--wide")==0) {
        int result=wide_vectors(argv[2],argv[3]);duoforge_context_destroy(context);return result;
    }
    if(argc==2&&strcmp(argv[1],"--context")==0) {
        uint8_t hash[32];(void)duoforge_context_fingerprint(context,hash);
        for(uint32_t i=0u;i<32u;++i)printf("%02x",hash[i]);
        printf(" %u %u\n",context->species_count,context->move_count);
        duoforge_context_destroy(context);return 0;
    }
    df_test t;df_test_begin(&t,"eval.graphs");
    if(argc==1)units(&t);
    else if(argc==5&&strcmp(argv[1],"--oom")==0) {
        uint8_t hash[32];
        if(!df_hex_to_bytes(argv[3],hash,sizeof hash)){duoforge_context_destroy(context);return 2;}
        const dfi_eval_shape *shape=dfi_eval_shape_lookup((uint32_t)strtoul(argv[4],NULL,10));
        if(!DF_CHECK(&t,shape!=NULL)){duoforge_context_destroy(context);return df_test_end(&t);}
        for(size_t fail=0u;fail<4u;++fail) {
            cold_allocations a={0u,0u,fail};dfi_eval_allocator allocator={cold_allocate,cold_release,&a};
            df_sentinel sentinel;duoforge_evaluator *model=(duoforge_evaluator *)&sentinel;duoforge_eval_error error;
            DF_CHECK_EQ_U64(&t,dfi_eval_load_descriptor(argv[2],hash,context,6u,UINT64_C(140737488355327),
                shape->graph,&allocator,&model,&error),DUOFORGE_E_OUT_OF_MEMORY);
            DF_CHECK(&t,model==(duoforge_evaluator *)&sentinel);DF_CHECK_EQ_U64(&t,a.frees,fail);
        }
    }
    else if((argc==6&&strcmp(argv[1],"--run")==0)||(argc==5&&strcmp(argv[1],"--refuse")==0)) {
        uint8_t hash[32];
        if(!df_hex_to_bytes(argv[3],hash,sizeof hash)){duoforge_context_destroy(context);return 2;}
        df_sentinel sentinel;duoforge_evaluator *model=(duoforge_evaluator *)&sentinel;
        duoforge_eval_error error;
        const duoforge_status st=duoforge_evaluator_load(argv[2],hash,context,6u,UINT64_C(140737488355327),&model,&error);
        if(strcmp(argv[1],"--refuse")==0) {
            DF_CHECK(&t,st!=DUOFORGE_OK&&model==(duoforge_evaluator *)&sentinel);
            DF_CHECK(&t,strcmp(error.reason,argv[4])==0);
            if(st==DUOFORGE_OK)duoforge_evaluator_destroy(model);
        } else {
            if(st!=DUOFORGE_OK)fprintf(stderr,"load refused: %u %s\n",(uint32_t)st,error.reason);
            if(DF_CHECK_EQ_U64(&t,st,DUOFORGE_OK)) {
                DF_CHECK(&t,remove(argv[2])==0);
                run_graph(&t,context,model,argv[4],argv[5]);
                duoforge_evaluator_destroy(model);
            }
        }
    }else{duoforge_context_destroy(context);return 2;}
    duoforge_context_destroy(context);return df_test_end(&t);
}
