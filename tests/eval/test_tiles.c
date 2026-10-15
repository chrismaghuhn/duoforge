#include "eval/tiles.h"
#include "core/sha256.h"
#include "support/check.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>

/* All synthetic parameters are constructed cold in memory and destroyed here.
 * E3g independently checks the graph arithmetic/loader against Python. These
 * tests compare the same scalar graph, including every stage, under scheduling. */
#ifdef DF_EVAL_ALLOC_HOOKS
static bool allocation_watch;
static uint64_t allocations;
static dfi_error_lock allocation_lock = DFI_ERROR_LOCK_INIT;
void *__real_malloc(size_t n);
void *__real_calloc(size_t n, size_t s);
void *__real_realloc(void *p, size_t n);
void __real_free(void *p);
void *__wrap_malloc(size_t n);
void *__wrap_calloc(size_t n, size_t s);
void *__wrap_realloc(void *p, size_t n);
void __wrap_free(void *p);
static void note_allocation(void)
{
    if (allocation_watch) {
        dfi_error_lock_enter(&allocation_lock); ++allocations; dfi_error_lock_leave(&allocation_lock);
    }
}
void *__wrap_malloc(size_t n) { note_allocation(); return __real_malloc(n); }
void *__wrap_calloc(size_t n, size_t s) { note_allocation(); return __real_calloc(n,s); }
void *__wrap_realloc(void *p, size_t n) { note_allocation(); return __real_realloc(p,n); }
void __wrap_free(void *p) { note_allocation(); __real_free(p); }
#endif
static void *allocate(size_t n, void *user) { (void)user; return calloc(1u,n); }
static void release(void *p, void *user) { (void)user; free(p); }
static void little(uint8_t *p, uint64_t value, uint32_t width)
{ for (uint32_t i=0u; i<width; ++i) p[i]=(uint8_t)(value>>(8u*i)); }
static duoforge_evaluator *synthetic(uint32_t id)
{
    const dfi_eval_shape *shape=dfi_eval_shape_lookup(id);
    if(shape==NULL)return NULL;
    const dfi_eval_graph *g=shape->graph;
    size_t bytes=256u+(size_t)g->tensor_count*128u;
    for(uint32_t t=0u;t<g->tensor_count;++t) {
        const dfi_eval_tensor_spec *s=&g->tensors[t];size_t n=1u;
        for(uint32_t d=0u;d<s->rank;++d)n*=s->dims[d];
        bytes=(bytes+7u)&~(size_t)7u;bytes+=n*((size_t)1u<<(s->dtype-1u));
        bytes=(bytes+7u)&~(size_t)7u;bytes+=(size_t)s->scale_count*8u;
    }
    duoforge_evaluator *m=calloc(1u,sizeof *m);
    if(m==NULL)return NULL;
    m->file=calloc(1u,bytes);m->lifetime=calloc(1u,sizeof *m->lifetime);
    if(m->file==NULL||m->lifetime==NULL){free(m->file);free(m->lifetime);free(m);return NULL;}
    m->graph=g;m->file_bytes=bytes;m->allocator=(dfi_eval_allocator){allocate,release,NULL};
#if defined(_WIN32)
    InitializeSRWLock(&m->lifetime->lock);
#else
    if(pthread_mutex_init(&m->lifetime->lock,NULL)!=0){free(m->file);free(m->lifetime);free(m);return NULL;}
#endif
    m->lifetime->references=1u;m->lifetime->owner=m;
    size_t cursor=256u+(size_t)g->tensor_count*128u;
    for(uint32_t t=0u;t<g->tensor_count;++t) {
        const dfi_eval_tensor_spec *s=&g->tensors[t];size_t n=1u;
        for(uint32_t d=0u;d<s->rank;++d)n*=s->dims[d];
        const uint32_t width=1u<<(s->dtype-1u);
        cursor=(cursor+7u)&~(size_t)7u;
        uint8_t *entry=m->file+256u+(size_t)t*128u;
        little(entry+56u,cursor,8u);little(entry+64u,n*width,8u);
        for(size_t j=0u;j<n;++j) {
            int64_t value=(int64_t)((j*17u+(size_t)t*11u)%7u)-3;
            if(t==0u)value=1024;
            else if(s->dtype==3u)value=strstr(s->name,".g")!=NULL?1024:((int64_t)(j%31u)-15);
            else if(s->dtype==4u)value=(int64_t)(j%37u)*17-200;
            little(m->file+cursor+j*width,(uint64_t)value,width);
        }
        cursor+=n*width;cursor=(cursor+7u)&~(size_t)7u;
        little(entry+72u,s->scale_count?cursor:0u,8u);
        for(uint32_t j=0u;j<s->scale_count;++j) {
            const uint32_t multiplier=s->dtype==1u&&s->rank==2u&&t<=5u?1024u:1u;
            little(m->file+cursor+8u*j,multiplier,4u);
            little(m->file+cursor+8u*j+4u,multiplier==1024u?0u:4u,4u);
        }
        cursor+=(size_t)s->scale_count*8u;
    }
    duoforge_eval_error error;
    if(dfi_eval_graph_bind(m,&error)!=DUOFORGE_OK){dfi_eval_model_release(m);return NULL;}
    return m;
}
static void observation(uint32_t key,uint32_t bits[1094])
{
    const dfi_eval_column *cols=dfi_eval_input_columns();
    for(uint32_t i=0u;i<1094u;++i) {
        const dfi_eval_column *c=&cols[i];
        const bool registered=((uint32_t)c->b+key)%3u!=0u;
        switch(c->group) {
        case DFI_EVAL_GROUP_PRESENT:case DFI_EVAL_GROUP_MOVE_COUNT:bits[i]=registered?UINT32_C(0x3f800000):0u;break;
        case DFI_EVAL_GROUP_OCCUPANT:bits[i]=c->c==(key+(uint32_t)c->a+c->b)%7u?UINT32_C(0x3f800000):0u;break;
        case DFI_EVAL_GROUP_SPECIES:case DFI_EVAL_GROUP_MOVES:bits[i]=key%2u?UINT32_C(0x37800080):0u;break;
        case DFI_EVAL_GROUP_ITEM:case DFI_EVAL_GROUP_ABILITY:bits[i]=key%2u?UINT32_C(0x3b808081):0u;break;
        case DFI_EVAL_GROUP_NATURE:bits[i]=0u;break;
        default:bits[i]=(i+key)%3u==0u?UINT32_C(0x3f000000):((i+key)%3u==1u?UINT32_C(0xbe800000):0u);break;
        }
    }
}
typedef struct row_hash { dfi_sha256_state sha; uint32_t stages; } row_hash;
static duoforge_status hash_stage(void *user,const char *stage,uint32_t index,uint32_t type,
    const void *values,uint32_t count)
{
    row_hash *h=user;uint8_t bytes[4];
    if(!dfi_sha256_update(&h->sha,(const uint8_t *)stage,strlen(stage)+1u))return DUOFORGE_E_INVARIANT;
    little(bytes,index,4u);if(!dfi_sha256_update(&h->sha,bytes,4u))return DUOFORGE_E_INVARIANT;
    little(bytes,type,4u);if(!dfi_sha256_update(&h->sha,bytes,4u))return DUOFORGE_E_INVARIANT;
    little(bytes,count,4u);if(!dfi_sha256_update(&h->sha,bytes,4u))return DUOFORGE_E_INVARIANT;
    for(uint32_t j=0u;j<count;++j) {
        uint32_t v=0u;
        if(type==1u)v=(uint32_t)(int32_t)((const int16_t *)values)[j];
        else if(type==2u)v=(uint32_t)((const int32_t *)values)[j];
        else if(type==3u)v=((const uint32_t *)values)[j];
        else if(type==4u)v=((const uint8_t *)values)[j];
        else return DUOFORGE_E_INVARIANT;
        little(bytes,v,4u);if(!dfi_sha256_update(&h->sha,bytes,4u))return DUOFORGE_E_INVARIANT;
    }
    ++h->stages;return DUOFORGE_OK;
}
typedef struct source_state {
    duoforge_eval_workspace *workspace;
    row_hash rows[33];uint32_t calls[33],workers[33];
    uint32_t offset;bool reorder,failures,all_refused,check_busy;
    uint32_t *large_calls;
} source_state;
static uint32_t key_for(const source_state *s,uint32_t leaf)
{ const uint32_t key=s->offset+leaf;return s->reorder?(key*17u+3u)%33u:key; }
static duoforge_status read_row(void *user,uint32_t leaf,uint32_t worker,uint32_t bits[1094],duoforge_eval_error *error)
{
    source_state *s=user;
    if(s->all_refused){++s->large_calls[leaf];return dfi_eval_error(error,DUOFORGE_E_INVALID_ARGUMENT,"input","synthetic_all_refused");}
    if(leaf>=33u)return DUOFORGE_E_INVARIANT;
    ++s->calls[leaf];s->workers[leaf]=worker;
    const size_t stride=s->workspace->model->graph->scratch_per_worker;
    const uint8_t *base=s->workspace->scratch+(size_t)worker*stride;
    const size_t pad=(128u-((size_t)(uintptr_t)base&127u))&127u;
    if((const uint8_t *)(const void *)bits!=base+pad)return DUOFORGE_E_INVARIANT;
    if(s->check_busy&&leaf==0u) {
        duoforge_eval_error detail;
        if(dfi_eval_workspace_acquire(s->workspace,s->workspace->model,s->workspace->model->context,
            0u,s->workspace->workers,&detail)!=DUOFORGE_E_UNSUPPORTED||strcmp(detail.reason,"eval_workspace_busy")!=0)
            return DUOFORGE_E_INVARIANT;
    }
    observation(key_for(s,leaf),bits);
    if(s->failures&&leaf==1u)bits[0]=UINT32_C(0x7fc00000);
    if(s->failures&&leaf==17u)return dfi_eval_error(error,DUOFORGE_E_INVALID_ARGUMENT,"input","synthetic_row_refused");
    return DUOFORGE_OK;
}
static duoforge_status trace_row(void *user,uint32_t leaf,const char *stage,uint32_t index,
    uint32_t type,const void *values,uint32_t count)
{
    source_state *s=user;
    if(s->failures&&leaf==32u&&strcmp(stage,"value")==0)return DUOFORGE_E_INVARIANT;
    return hash_stage(&s->rows[leaf],stage,index,type,values,count);
}
static void reset_source(source_state *s)
{
    memset(s->calls,0,sizeof s->calls);memset(s->workers,0xff,sizeof s->workers);
    for(uint32_t i=0u;i<33u;++i){dfi_sha256_init(&s->rows[i].sha);s->rows[i].stages=0u;}
}
static duoforge_status unnamed_source(void *user,uint32_t leaf,uint32_t worker,uint32_t bits[1094],duoforge_eval_error *error)
{ (void)user;(void)leaf;(void)worker;(void)bits;(void)error;return DUOFORGE_E_CAPACITY; }
static bool bytes_are(const uint8_t *p,size_t n,uint8_t value)
{ for(size_t i=0u;i<n;++i)if(p[i]!=value)return false;return true; }
static uint64_t runs,compared_rows;
static void run_case(df_test *t,const duoforge_evaluator *m,duoforge_eval_workspace *w,dfi_pool *pool,
    uint32_t count,uint32_t offset,bool reorder,bool failures,const int32_t expected[33],const uint8_t hashes[33][32])
{
    source_state s;memset(&s,0,sizeof s);s.workspace=w;s.offset=offset;s.reorder=reorder;s.failures=failures;s.check_busy=true;
    reset_source(&s);const dfi_eval_row_source source={read_row,trace_row,&s};
    duoforge_status statuses[35];int32_t values[35];
    for(uint32_t i=0u;i<35u;++i){statuses[i]=DUOFORGE_E_EXHAUSTED;values[i]=INT32_MIN;}
    memset(w->scratch,0xa5,w->scratch_bytes);
    duoforge_eval_error error;
#ifdef DF_EVAL_ALLOC_HOOKS
    allocations=0u;allocation_watch=true;
#endif
    const duoforge_status st=dfi_eval_tiles(m,w,pool,m->context,count,&source,statuses,values,&error);
#ifdef DF_EVAL_ALLOC_HOOKS
    allocation_watch=false;DF_CHECK_EQ_U64(t,allocations,0u);
#endif
    ++runs;
    if(failures){DF_CHECK(t,st!=DUOFORGE_OK);DF_CHECK_EQ_U64(t,error.leaf,1u);DF_CHECK(t,strstr(error.reason,"eval_input_scalar:")!=NULL);}
    else {DF_CHECK_EQ_U64(t,st,DUOFORGE_OK);DF_CHECK_EQ_U64(t,error.leaf,UINT32_MAX);}
    if(count==0u)DF_CHECK(t,bytes_are(w->scratch,w->scratch_bytes,0xa5));
    const uint32_t tiles=count/16u+(count%16u!=0u?1u:0u),workers=dfi_pool_workers(pool);
    for(uint32_t leaf=0u;leaf<count;++leaf) {
        DF_CHECK_EQ_U64(t,s.calls[leaf],1u);
        uint32_t expected_worker=UINT32_MAX;
        for(uint32_t worker=0u;worker<workers;++worker) {
            const uint32_t begin=(uint32_t)(((uint64_t)tiles*worker)/workers);
            const uint32_t end=(uint32_t)(((uint64_t)tiles*(worker+1u))/workers);
            if(leaf/16u>=begin&&leaf/16u<end)expected_worker=worker;
        }
        DF_CHECK_EQ_U64(t,s.workers[leaf],expected_worker);
        if(failures&&(leaf==1u||leaf==17u||leaf==32u)) {
            DF_CHECK(t,statuses[leaf]!=DUOFORGE_OK&&values[leaf]==INT32_MIN);continue;
        }
        const uint32_t key=key_for(&s,leaf);uint8_t hash[32];
        DF_CHECK_EQ_U64(t,statuses[leaf],DUOFORGE_OK);DF_CHECK(t,values[leaf]==expected[key]);
        DF_CHECK_EQ_U64(t,s.rows[leaf].stages,189u+4u*dfi_eval_shape_lookup(m->graph->id)->layers);
        DF_CHECK(t,dfi_sha256_final(&s.rows[leaf].sha,hash));DF_CHECK_BYTES(t,hash,hashes[key],32u,"scalar intermediates");
        ++compared_rows;
    }
    for(uint32_t i=count;i<35u;++i)DF_CHECK(t,statuses[i]==DUOFORGE_E_EXHAUSTED&&values[i]==INT32_MIN);
    for(uint32_t i=count;i<33u;++i)DF_CHECK_EQ_U64(t,s.calls[i],0u);
    for(uint32_t worker=0u;worker<workers;++worker) {
        const uint32_t begin=(uint32_t)(((uint64_t)tiles*worker)/workers);
        const uint32_t end=(uint32_t)(((uint64_t)tiles*(worker+1u))/workers);
        if(begin==end)DF_CHECK(t,bytes_are(w->scratch+(size_t)worker*m->graph->scratch_per_worker,m->graph->scratch_per_worker,0xa5));
        DF_CHECK(t,bytes_are(w->scratch+(size_t)(worker+1u)*m->graph->scratch_per_worker-32u,32u,0xa5));
    }
}
static void preflight(df_test *t,const duoforge_evaluator *m,duoforge_eval_workspace *w,dfi_pool *pool)
{
    source_state s;memset(&s,0,sizeof s);s.workspace=w;reset_source(&s);
    dfi_eval_row_source source={read_row,trace_row,&s};duoforge_eval_error error;
    duoforge_status status=DUOFORGE_E_EXHAUSTED;int32_t value=77;
    memset(w->scratch,0x6a,w->scratch_bytes);
    DF_CHECK_EQ_U64(t,dfi_eval_tiles(NULL,w,pool,m->context,1u,&source,&status,&value,&error),DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK_EQ_U64(t,dfi_eval_tiles(m,w,pool,m->context,1u,NULL,&status,&value,&error),DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK_EQ_U64(t,dfi_eval_tiles(m,w,pool,m->context,1u,&source,NULL,&value,&error),DUOFORGE_E_NULL_ARGUMENT);
    source.read=NULL;
    DF_CHECK_EQ_U64(t,dfi_eval_tiles(m,w,pool,m->context,1u,&source,&status,&value,&error),DUOFORGE_E_NULL_ARGUMENT);
    source.read=read_row;
    uint8_t wrong[32];memcpy(wrong,m->context,32u);wrong[0]^=1u;
    DF_CHECK_EQ_U64(t,dfi_eval_tiles(m,w,pool,wrong,1u,&source,&status,&value,&error),DUOFORGE_E_CONTEXT_MISMATCH);
    duoforge_evaluator other_model=*m;
    DF_CHECK_EQ_U64(t,dfi_eval_tiles(&other_model,w,pool,m->context,1u,&source,&status,&value,&error),DUOFORGE_E_CONTEXT_MISMATCH);
    other_model.parameters=NULL;
    DF_CHECK_EQ_U64(t,dfi_eval_tiles(&other_model,w,pool,m->context,1u,&source,&status,&value,&error),DUOFORGE_E_UNSUPPORTED);
    dfi_eval_graph unknown=*m->graph;unknown.id=9999u;other_model.graph=&unknown;
    DF_CHECK_EQ_U64(t,dfi_eval_tiles(&other_model,w,pool,m->context,1u,&source,&status,&value,&error),DUOFORGE_E_UNSUPPORTED);
    DF_CHECK_EQ_U64(t,dfi_eval_tiles(m,w,pool,m->context,34u,&source,&status,&value,&error),DUOFORGE_E_CAPACITY);
    DF_CHECK_EQ_U64(t,dfi_eval_tiles(m,w,pool,m->context,UINT32_MAX,&source,&status,&value,&error),DUOFORGE_E_CAPACITY);
    dfi_pool *other=dfi_pool_create(w->workers==1u?2u:1u);
    if(DF_CHECK(t,other!=NULL)) {
        DF_CHECK_EQ_U64(t,dfi_eval_tiles(m,w,other,m->context,1u,&source,&status,&value,&error),DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(t,strcmp(error.reason,"eval_workspace_workers")==0);dfi_pool_destroy(other);
    }
    DF_CHECK_EQ_U64(t,dfi_eval_workspace_acquire(w,m,m->context,0u,w->workers,&error),DUOFORGE_OK);
    DF_CHECK_EQ_U64(t,dfi_eval_tiles(m,w,pool,m->context,1u,&source,&status,&value,&error),DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t,strcmp(error.reason,"eval_workspace_busy")==0);dfi_eval_workspace_release(w);
    const size_t bytes=w->scratch_bytes;w->scratch_bytes=1u;
    DF_CHECK_EQ_U64(t,dfi_eval_tiles(m,w,pool,m->context,1u,&source,&status,&value,&error),DUOFORGE_E_CAPACITY);
    DF_CHECK(t,strcmp(error.reason,"eval_tiles_capacity")==0);w->scratch_bytes=bytes;
    DF_CHECK_EQ_U64(t,dfi_eval_tiles(m,w,pool,m->context,0u,NULL,NULL,NULL,&error),DUOFORGE_OK);
    DF_CHECK(t,bytes_are(w->scratch,w->scratch_bytes,0x6a));
    DF_CHECK(t,status==DUOFORGE_E_EXHAUSTED&&value==77&&error.leaf==UINT32_MAX);
    for(uint32_t i=0u;i<33u;++i)DF_CHECK_EQ_U64(t,s.calls[i],0u);
    source.read=unnamed_source;
    DF_CHECK_EQ_U64(t,dfi_eval_tiles(m,w,pool,m->context,1u,&source,&status,&value,&error),DUOFORGE_E_CAPACITY);
    DF_CHECK(t,status==DUOFORGE_E_CAPACITY&&value==77&&error.leaf==0u);
    DF_CHECK(t,strcmp(error.phase,"input")==0&&strcmp(error.reason,"eval_row_source_refused")==0);
}
static void maximum(df_test *t,const duoforge_evaluator *m)
{
    duoforge_eval_workspace *w=NULL;duoforge_eval_error error;dfi_pool *pool=dfi_pool_create(32u);
    if(!DF_CHECK(t,pool!=NULL))return;
    if(!DF_CHECK_EQ_U64(t,duoforge_eval_workspace_create(m,65536u,32u,&w,&error),DUOFORGE_OK)){dfi_pool_destroy(pool);return;}
    duoforge_status *statuses=calloc(65538u,sizeof *statuses);int32_t *values=calloc(65538u,sizeof *values);
    uint32_t *calls=calloc(65536u,sizeof *calls);
    if(DF_CHECK(t,statuses!=NULL&&values!=NULL&&calls!=NULL)) {
        for(uint32_t i=0u;i<65538u;++i){statuses[i]=DUOFORGE_E_EXHAUSTED;values[i]=77;}
        source_state s;memset(&s,0,sizeof s);s.workspace=w;s.all_refused=true;s.large_calls=calls;
        const dfi_eval_row_source source={read_row,NULL,&s};
        DF_CHECK_EQ_U64(t,dfi_eval_tiles(m,w,pool,m->context,65537u,&source,statuses,values,&error),DUOFORGE_E_CAPACITY);
#ifdef DF_EVAL_ALLOC_HOOKS
        allocations=0u;allocation_watch=true;
#endif
        const duoforge_status st=dfi_eval_tiles(m,w,pool,m->context,65536u,&source,statuses,values,&error);
#ifdef DF_EVAL_ALLOC_HOOKS
        allocation_watch=false;DF_CHECK_EQ_U64(t,allocations,0u);
#endif
        DF_CHECK_EQ_U64(t,st,DUOFORGE_E_INVALID_ARGUMENT);DF_CHECK_EQ_U64(t,error.leaf,0u);
        DF_CHECK(t,strcmp(error.reason,"synthetic_all_refused")==0);
        for(uint32_t i=0u;i<65536u;++i)DF_CHECK(t,statuses[i]==DUOFORGE_E_INVALID_ARGUMENT&&values[i]==77&&calls[i]==1u);
        DF_CHECK(t,statuses[65536]==DUOFORGE_E_EXHAUSTED&&values[65536]==77&&values[65537]==77);
    }
    free(statuses);free(values);free(calls);dfi_pool_destroy(pool);
    DF_CHECK_EQ_U64(t,duoforge_eval_workspace_destroy(w,&error),DUOFORGE_OK);
}
static void graph_cases(df_test *t,uint32_t id,bool race)
{
    duoforge_evaluator *m=synthetic(id);
    if(!DF_CHECK(t,m!=NULL))return;
    const dfi_eval_shape *shape=dfi_eval_shape_lookup(id);
    duoforge_eval_workspace *scalar=NULL;duoforge_eval_error error;
    if(!DF_CHECK_EQ_U64(t,duoforge_eval_workspace_create(m,33u,1u,&scalar,&error),DUOFORGE_OK)){dfi_eval_model_release(m);return;}
    int32_t expected[33];uint8_t hashes[33][32];uint32_t bits[1094];
    DF_CHECK_EQ_U64(t,dfi_eval_workspace_acquire(scalar,m,m->context,33u,1u,&error),DUOFORGE_OK);
    dfi_sha256_state stream;dfi_sha256_init(&stream);
    for(uint32_t row=0u;row<33u;++row) {
        observation(row,bits);row_hash h;dfi_sha256_init(&h.sha);h.stages=0u;
        const dfi_eval_trace trace={hash_stage,&h};
        DF_CHECK_EQ_U64(t,dfi_eval_graph_row(m,scalar->scratch,scalar->scratch_bytes,row%16u,bits,&trace,&expected[row],&error),DUOFORGE_OK);
        DF_CHECK_EQ_U64(t,h.stages,189u+4u*shape->layers);DF_CHECK(t,dfi_sha256_final(&h.sha,hashes[row]));
        uint8_t value[4];little(value,(uint32_t)expected[row],4u);
        DF_CHECK(t,dfi_sha256_update(&stream,value,4u));DF_CHECK(t,dfi_sha256_update(&stream,hashes[row],32u));
    }
    bool different=false;for(uint32_t row=1u;row<33u;++row)if(expected[row]!=expected[0])different=true;
    DF_CHECK(t,different);uint8_t digest[32];DF_CHECK(t,dfi_sha256_final(&stream,digest));
    dfi_eval_workspace_release(scalar);
    printf("tile_scalar graph=%u SHA256=",id);for(uint32_t i=0u;i<32u;++i)printf("%02x",digest[i]);puts("");
    const uint32_t counts[]={0u,1u,15u,16u,17u,31u,32u,33u};
    for(uint32_t workers=1u;workers<=32u;++workers) {
        if(race&&workers!=1u&&workers!=2u&&workers!=4u&&workers!=8u&&workers!=16u&&workers!=32u)continue;
        dfi_pool *pool=dfi_pool_create(workers);duoforge_eval_workspace *w=NULL;
        if(!DF_CHECK(t,pool!=NULL))continue;
        if(!DF_CHECK_EQ_U64(t,duoforge_eval_workspace_create(m,33u,workers,&w,&error),DUOFORGE_OK)){dfi_pool_destroy(pool);continue;}
        preflight(t,m,w,pool);
        if(!race&&(id==1002u||workers==1u||workers==4u||workers==32u)) {
            for(size_t c=0u;c<sizeof counts/sizeof counts[0];++c)
                run_case(t,m,w,pool,counts[c],0u,false,false,expected,(const uint8_t (*)[32])hashes);
        }else run_case(t,m,w,pool,17u,0u,false,false,expected,(const uint8_t (*)[32])hashes);
        if(workers==1u||workers==4u||workers==32u) {
            run_case(t,m,w,pool,33u,0u,true,false,expected,(const uint8_t (*)[32])hashes);
            run_case(t,m,w,pool,33u,0u,false,true,expected,(const uint8_t (*)[32])hashes);
            const uint32_t chunks[][4]={{1u,15u,16u,1u},{0u,16u,17u,0u},{7u,8u,9u,9u}};
            for(uint32_t part=0u;part<3u;++part) {
                uint32_t offset=0u;
                for(uint32_t c=0u;c<4u;++c) {
                    run_case(t,m,w,pool,chunks[part][c],offset,false,false,expected,(const uint8_t (*)[32])hashes);
                    offset+=chunks[part][c];
                }
                DF_CHECK_EQ_U64(t,offset,33u);
            }
        }
        dfi_pool_destroy(pool);DF_CHECK_EQ_U64(t,duoforge_eval_workspace_destroy(w,&error),DUOFORGE_OK);
    }
    maximum(t,m);
    printf("tile_resources graph=%u worker=%zu graph=%zu diagnostic=256\n",id,m->graph->scratch_per_worker,dfi_eval_graph_scratch(shape));
    DF_CHECK_EQ_U64(t,duoforge_eval_workspace_destroy(scalar,&error),DUOFORGE_OK);dfi_eval_model_release(m);
}
int main(int argc,char **argv)
{
    df_test t;df_test_begin(&t,"eval.tiles");
    if(argc==2&&strcmp(argv[1],"--race")==0){graph_cases(&t,1001u,true);graph_cases(&t,1002u,true);graph_cases(&t,1003u,true);}
    else if(argc==2)graph_cases(&t,(uint32_t)strtoul(argv[1],NULL,10),false);
    else {
        duoforge_eval_error error;
        DF_CHECK_EQ_U64(&t,dfi_eval_tiles(NULL,NULL,NULL,NULL,0u,NULL,NULL,NULL,&error),DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t,strcmp(error.reason,"eval_tiles_argument")==0&&error.leaf==UINT32_MAX);
    }
    printf("tile_totals runs=%llu compared_rows=%llu\n",(unsigned long long)runs,(unsigned long long)compared_rows);
    return df_test_end(&t);
}
