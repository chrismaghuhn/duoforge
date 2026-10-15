/* Private offline E4 bridge. No new public API, discovery or adoption.
 * stdin: repeated LE u32 count (1..16), count encoder-6 binary32 rows;
 * zero count ends. stdout: LE count then (status, signed Q12.20 bits)/row.
 * Optional trace file uses the independent graph oracle's canonical frames.
 * All I/O is offline tooling, outside the battle/inference hot path. */
#include "eval/graph.h"
#include "state/context_internal.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
static FILE *file_open(const char *path, const char *mode)
{
#if defined(_MSC_VER)
    FILE *f = NULL;
    return fopen_s(&f,path,mode) == 0 ? f : NULL;
#else
    return fopen(path,mode);
#endif
}
static bool get32(FILE *f,uint32_t *out)
{
    uint8_t b[4];
    if(fread(b,1u,4u,f)!=4u)return false;
    *out=(uint32_t)b[0]|(uint32_t)b[1]<<8u|(uint32_t)b[2]<<16u|(uint32_t)b[3]<<24u;
    return true;
}
static bool put32(FILE *f,uint32_t x)
{
    uint8_t b[4];
    for(uint32_t i=0u;i<4u;++i)b[i]=(uint8_t)(x>>(8u*i));
    return fwrite(b,1u,4u,f)==4u;
}
typedef struct trace_sink { FILE *file; uint32_t row; } trace_sink;
static duoforge_status emit(void *user,const char *stage,uint32_t index,uint32_t type,
                           const void *data,uint32_t count)
{
    trace_sink *out=user;const uint32_t n=(uint32_t)strlen(stage);
    if(!put32(out->file,out->row)||!put32(out->file,index)||!put32(out->file,count)||!put32(out->file,n)||
       fwrite(stage,1u,n,out->file)!=n)return DUOFORGE_E_INVARIANT;
    for(uint32_t i=0u;i<count;++i) {
        uint32_t value;
        if(type==1u)value=(uint32_t)((const int16_t *)data)[i];
        else if(type==2u)value=(uint32_t)((const int32_t *)data)[i];
        else if(type==3u)value=((const uint32_t *)data)[i];
        else if(type==4u)value=((const uint8_t *)data)[i];
        else return DUOFORGE_E_INVARIANT;
        if(!put32(out->file,value))return DUOFORGE_E_INVARIANT;
    }
    return DUOFORGE_OK;
}
static bool number(const char *text,uint32_t *out)
{
    char *end=NULL;unsigned long value=strtoul(text,&end,10);
    if(text[0]=='\0'||*end!='\0'||value>UINT32_MAX)return false;
    *out=(uint32_t)value;return true;
}
int main(int argc,char **argv)
{
    if(argc==2&&strcmp(argv[1],"--identity")==0) {
        (void)printf("%s %s %s %s\n",DFE4_COMPILER,DFE4_PLATFORM,DFE4_CONFIG,DFE4_IPO);
        return 0;
    }
    uint32_t kind=0u,trace_count=0u;
    const bool context=argc==3&&strcmp(argv[1],"--context")==0;
    if(!(context||argc==5||argc==7)||!number(argv[context?2:3],&kind))return 2;
    if(argc==7&&!number(argv[6],&trace_count))return 2;
    duoforge_context_config cfg={kind,6u,4u,0u,0u,NULL};
    duoforge_context *ctx=NULL;duoforge_evaluator *model=NULL;duoforge_eval_workspace *workspace=NULL;
    duoforge_eval_error error;memset(&error,0,sizeof error);
    if(duoforge_context_create(&cfg,&ctx)!=DUOFORGE_OK)return 2;
    uint8_t fingerprint[32];
    if(duoforge_context_fingerprint(ctx,fingerprint)!=DUOFORGE_OK){duoforge_context_destroy(ctx);return 2;}
    if(context) {
        for(uint32_t i=0u;i<32u;++i)(void)printf("%02x",fingerprint[i]);
        (void)printf(" %u %u %u %u\n",ctx->species_count,ctx->move_count,
                     DUOFORGE_SEMANTICS_ID,DUOFORGE_CONTEXT_SCHEMA_VERSION);
        duoforge_context_destroy(ctx);return 0;
    }
    if(strcmp(argv[1],"--run")!=0||strlen(argv[4])!=64u){duoforge_context_destroy(ctx);return 2;}
    uint8_t expected[32];
    for(uint32_t i=0u;i<32u;++i) {
        uint32_t value=0u;
        for(uint32_t j=0u;j<2u;++j) {
            const char c=argv[4][2u*i+j];
            if(!((c>='0'&&c<='9')||(c>='a'&&c<='f'))){duoforge_context_destroy(ctx);return 2;}
            value=16u*value+(uint32_t)(c<='9'?c-'0':c-'a'+10);
        }
        expected[i]=(uint8_t)value;
    }
    int failed=1;trace_sink sink={NULL,0u};
    if(argc==7) {sink.file=file_open(argv[5],"wb");if(sink.file==NULL)goto done;}
    if(duoforge_evaluator_load(argv[2],expected,ctx,6u,UINT64_C(0x082000835233ffff),&model,&error)!=DUOFORGE_OK)goto done;
    if(duoforge_eval_workspace_create(model,16u,1u,&workspace,&error)!=DUOFORGE_OK)goto done;
    if(dfi_eval_workspace_acquire(workspace,model,fingerprint,16u,1u,&error)!=DUOFORGE_OK)goto done;
#ifdef _WIN32
    if(_setmode(_fileno(stdin),_O_BINARY)==-1||_setmode(_fileno(stdout),_O_BINARY)==-1)goto release;
#endif
    for(;;) {
        uint32_t count=0u;
        if(!get32(stdin,&count)||count>16u)goto release;
        if(count==0u){failed=0;break;}
        if(!put32(stdout,count))goto release;
        for(uint32_t row=0u;row<count;++row) {
            uint32_t bits[1094];int32_t value=0;
            for(uint32_t j=0u;j<1094u;++j)if(!get32(stdin,&bits[j]))goto release;
            const dfi_eval_trace trace={emit,&sink};
            duoforge_status status=dfi_eval_graph_row(model,workspace->scratch,workspace->scratch_bytes,
                row%16u,bits,sink.row<trace_count?&trace:NULL,&value,&error);
            if(!put32(stdout,status)||!put32(stdout,(uint32_t)value))goto release;
            ++sink.row;
        }
        if(fflush(stdout)!=0)goto release;
    }
release:
    dfi_eval_workspace_release(workspace);
done:
    if(failed!=0)(void)fprintf(stderr,"bc6_runner_refused: %s\n",error.reason);
    if(sink.file!=NULL&&fclose(sink.file)!=0)failed=1;
    (void)duoforge_eval_workspace_destroy(workspace,NULL);
    duoforge_evaluator_destroy(model);duoforge_context_destroy(ctx);
    return failed;
}
