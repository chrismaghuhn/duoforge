#include "eval/normalization.h"
#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <stdbool.h>
#include <stdlib.h>
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


static uint32_t checks, failures;
#define CHECK(x) do { ++checks; if (!(x)) { ++failures; fprintf(stderr,"line %u: %s\n",(uint32_t)__LINE__,#x); } } while (0)
static const dfi_eval_scale unity = {1,0};
static void basic(void)
{
    int32_t x[4] = {-2,-1,1,2}, gamma[4] = {1,1,1,1}, beta[4] = {0,0,0,0};
    int32_t scratch[4], out[4] = {77,77,77,77};
    dfi_eval_normalization p = {1,0,0,{1,0},{1,0}};
    CHECK(dfi_eval_layernorm32(x,gamma,beta,4,p,scratch,4,out)==DUOFORGE_OK);
    CHECK(out[0]==-1 && out[1]==0 && out[2]==0 && out[3]==1);
    int32_t constant[4]={INT32_MIN,INT32_MIN,INT32_MIN,INT32_MIN};
    int32_t offsets[4]={INT32_MIN,-1,1,INT32_MAX};
    CHECK(dfi_eval_layernorm32(constant,gamma,offsets,4,p,scratch,4,out)==DUOFORGE_OK);
    CHECK(memcmp(out,offsets,sizeof(out))==0);
    /* Nonzero variance beyond uint64 sum; root fractional scale survives. */
    int32_t extreme[4]={INT32_MIN,INT32_MAX,INT32_MIN,INT32_MAX};
    p.sqrt_shift=31; p.numerator_shift=31;
    CHECK(dfi_eval_layernorm32(extreme,gamma,beta,4,p,scratch,4,out)==DUOFORGE_OK);
    CHECK(out[0]==-1 && out[1]==1 && out[2]==-1 && out[3]==1);
    /* -1/2 ties rounds mean to even zero, producing signed negative tie. */
    int32_t tie[2]={-1,0}; int32_t pair_gamma[2]={3,-3},pair_beta[2]={1,-1};
    p.sqrt_shift=0; p.numerator_shift=1; p.gamma_scale=(dfi_eval_scale){1,1};
    CHECK(dfi_eval_layernorm32(tie,pair_gamma,pair_beta,2,p,scratch,4,out)==DUOFORGE_OK);
    CHECK(out[0]==-2 && out[1]==-1);
    for (uint32_t i=0;i<4;++i) out[i]=77;
    p.epsilon=0;
    CHECK(dfi_eval_layernorm32(x,gamma,beta,4,p,scratch,4,out)==DUOFORGE_E_INVALID_ARGUMENT);
    CHECK(out[0]==77 && out[3]==77);
    p.epsilon=1; p.sqrt_shift=32;
    CHECK(dfi_eval_layernorm32(x,gamma,beta,4,p,scratch,4,out)==DUOFORGE_E_INVALID_ARGUMENT);
    p.sqrt_shift=0;p.numerator_shift=64;
    CHECK(dfi_eval_layernorm32(x,gamma,beta,4,p,scratch,4,out)==DUOFORGE_E_INVALID_ARGUMENT);
    p.numerator_shift=0;p.gamma_scale.multiplier=0;
    CHECK(dfi_eval_layernorm32(x,gamma,beta,4,p,scratch,4,out)==DUOFORGE_E_INVALID_ARGUMENT);
    p.gamma_scale=unity;p.output_scale.shift=64;
    CHECK(dfi_eval_layernorm32(x,gamma,beta,4,p,scratch,4,out)==DUOFORGE_E_INVALID_ARGUMENT);
    p.output_scale=unity;
    CHECK(dfi_eval_layernorm32(x,gamma,beta,4,p,scratch,3,out)==DUOFORGE_E_CAPACITY);
    CHECK(dfi_eval_layernorm32(x,gamma,beta,0,p,scratch,4,out)==DUOFORGE_E_INVALID_ARGUMENT);
    CHECK(dfi_eval_layernorm32(x,gamma,NULL,4,p,scratch,4,out)==DUOFORGE_E_NULL_ARGUMENT);
    CHECK(dfi_eval_layernorm32(x,gamma,beta,4,p,x,4,out)==DUOFORGE_E_INVALID_ARGUMENT);
    /* Late range refusal publishes none of the earlier valid channels. */
    int32_t overflow_gamma[4]={1,1,1,INT32_MAX}, overflow_beta[4]={0,0,0,1};
    CHECK(dfi_eval_layernorm32(x,overflow_gamma,overflow_beta,4,p,scratch,4,out)==DUOFORGE_E_EXHAUSTED);
    CHECK(out[0]==77 && out[3]==77);
    /* Legal alias of output and input, after complete scratch calculation. */
    CHECK(dfi_eval_layernorm32(x,gamma,beta,4,p,scratch,4,x)==DUOFORGE_OK);
    CHECK(x[0]==-1 && x[3]==1);
}
static void roots(void)
{
    uint64_t root=999;
    CHECK(dfi_eval_sqrt128(0,0,&root)==DUOFORGE_OK && root==0);
    CHECK(dfi_eval_sqrt128(0,1,&root)==DUOFORGE_OK && root==1);
    CHECK(dfi_eval_sqrt128(0,2,&root)==DUOFORGE_OK && root==1);
    CHECK(dfi_eval_sqrt128(0,3,&root)==DUOFORGE_OK && root==2);
    CHECK(dfi_eval_sqrt128(0,6,&root)==DUOFORGE_OK && root==2);
    CHECK(dfi_eval_sqrt128(0,7,&root)==DUOFORGE_OK && root==3);
    CHECK(dfi_eval_sqrt128(1,0,&root)==DUOFORGE_OK && root==UINT64_C(4294967296));
    CHECK(dfi_eval_sqrt128(UINT64_MAX-1u,1,&root)==DUOFORGE_OK && root==UINT64_MAX);
    root=999;
    CHECK(dfi_eval_sqrt128(UINT64_MAX,UINT64_MAX,&root)==DUOFORGE_E_EXHAUSTED && root==999);
    CHECK(dfi_eval_sqrt128(0,1,NULL)==DUOFORGE_E_NULL_ARGUMENT);
}
static void residuals(void)
{
    int32_t a[4]={INT32_MIN,INT32_MAX,-3,3},b[4]={0,0,0,0},scratch[4],out[4];
    int16_t small[4];
    CHECK(dfi_eval_residual32(a,b,4,unity,unity,unity,scratch,4,out)==DUOFORGE_OK);
    CHECK(memcmp(out,a,sizeof(out))==0);
    CHECK(dfi_eval_residual16(a,b,4,unity,unity,unity,scratch,4,small)==DUOFORGE_OK);
    CHECK(small[0]==INT16_MIN && small[1]==INT16_MAX && small[2]==-3 && small[3]==3);
    dfi_eval_scale half={1,1};
    CHECK(dfi_eval_residual32(a,b,4,half,unity,unity,scratch,4,out)==DUOFORGE_OK);
    CHECK(out[2]==-2 && out[3]==2);
    b[3]=INT32_MAX;
    for(uint32_t i=0;i<4;++i)out[i]=77;
    CHECK(dfi_eval_residual32(a,b,4,unity,unity,unity,scratch,4,out)==DUOFORGE_E_EXHAUSTED);
    CHECK(out[0]==77 && out[3]==77);
    CHECK(dfi_eval_residual16(a,b,4,unity,unity,unity,scratch,4,small)==DUOFORGE_OK);
    CHECK(small[3]==INT16_MAX);
    b[0]=INT32_MIN;
    dfi_eval_scale huge={UINT32_MAX,0};
    CHECK(dfi_eval_residual16(a,b,4,huge,huge,unity,scratch,4,small)==DUOFORGE_E_EXHAUSTED);
    CHECK(dfi_eval_residual32(a,b,4,(dfi_eval_scale){0,0},unity,unity,scratch,4,out)==DUOFORGE_E_INVALID_ARGUMENT);
    CHECK(dfi_eval_residual32(a,b,4,unity,unity,unity,scratch,3,out)==DUOFORGE_E_CAPACITY);
}
static void warm_allocations(void)
{
    int32_t x[4]={-3,-1,1,3}, gamma[4]={1,1,1,1},beta[4]={0,0,0,0},scratch[4],out[4];
    int16_t small[4]; uint64_t root;
    dfi_eval_normalization p={1,7,7,{1,0},{1,0}};
    dfi_eval_normalization_stats stats;
    CHECK(dfi_eval_layernorm32(x,gamma,beta,4,p,scratch,4,out)==DUOFORGE_OK);
#ifdef DF_EVAL_ALLOC_HOOKS
    allocations=0;allocation_watch=true;
#endif
    uint32_t bad=0;
    for(uint32_t i=0;i<1024;++i) {
        if(dfi_eval_layernorm_moments(x,4,p,&stats)!=DUOFORGE_OK)++bad;
        if(dfi_eval_layernorm32(x,gamma,beta,4,p,scratch,4,out)!=DUOFORGE_OK)++bad;
        if(dfi_eval_residual32(x,beta,4,unity,unity,unity,scratch,4,out)!=DUOFORGE_OK)++bad;
        if(dfi_eval_residual16(x,beta,4,unity,unity,unity,scratch,4,small)!=DUOFORGE_OK)++bad;
        if(dfi_eval_sqrt128(UINT64_C(0x7fffffffffffffff),UINT64_MAX,&root)!=DUOFORGE_OK)++bad;
    }
#ifdef DF_EVAL_ALLOC_HOOKS
    allocation_watch=false;
    CHECK(allocations==0);
#endif
    CHECK(bad==0);
}

/* Text transport is test-only; Python arbitrary-precision oracle chooses inputs
   and expected outputs independently. No real parameters or generated files. */
static int vectors(void)
{
    char op; uint32_t n,rs,ns,gm,gs,om,os,lm,ls,rm,ss; uint64_t epsilon,hi,lo;
    int32_t x[64],g[64],b[64],scratch[64],out[64]; int16_t small[64];
    while(scanf(" %c",&op)==1) {
        duoforge_status st; uint64_t root=0;
        if(op=='S') {
            if(scanf("%"SCNu64" %"SCNu64,&hi,&lo)!=2)return 2;
            st=dfi_eval_sqrt128(hi,lo,&root);
            printf("%u %"PRIu64"\n",(uint32_t)st,root);continue;
        }
        if(op=='N'||op=='M') {
            if(scanf("%u %"SCNu64" %u %u %u %u %u %u",&n,&epsilon,&rs,&ns,&gm,&gs,&om,&os)!=8||n>64)return 2;
            for(uint32_t i=0;i<n;++i)if(scanf("%"SCNd32,&x[i])!=1)return 2;
            for(uint32_t i=0;i<n;++i)if(scanf("%"SCNd32,&g[i])!=1)return 2;
            for(uint32_t i=0;i<n;++i)if(scanf("%"SCNd32,&b[i])!=1)return 2;
            dfi_eval_normalization parameters={epsilon,rs,ns,{gm,gs},{om,os}};
            if(op=='M') {
                dfi_eval_normalization_stats stats;
                st=dfi_eval_layernorm_moments(x,n,parameters,&stats);
                printf("%u",(uint32_t)st);
                if(st==DUOFORGE_OK)printf(" %"PRId64" %"PRIu64" %"PRIu64" %"PRIu64,stats.mean,stats.variance_hi,stats.variance_lo,stats.denominator);
                putchar('\n');continue;
            }
            st=dfi_eval_layernorm32(x,g,b,n,parameters,scratch,64,out);
        }else if(op=='R'||op=='T') {
            if(scanf("%u %u %u %u %u %u %u",&n,&lm,&ls,&rm,&ss,&om,&os)!=7||n>64)return 2;
            for(uint32_t i=0;i<n;++i)if(scanf("%"SCNd32,&x[i])!=1)return 2;
            for(uint32_t i=0;i<n;++i)if(scanf("%"SCNd32,&g[i])!=1)return 2;
            st=op=='R'?dfi_eval_residual32(x,g,n,(dfi_eval_scale){lm,ls},(dfi_eval_scale){rm,ss},(dfi_eval_scale){om,os},scratch,64,out)
                      :dfi_eval_residual16(x,g,n,(dfi_eval_scale){lm,ls},(dfi_eval_scale){rm,ss},(dfi_eval_scale){om,os},scratch,64,small);
        }else return 2;
        printf("%u",(uint32_t)st);
        if(st==DUOFORGE_OK)for(uint32_t i=0;i<n;++i)printf(" %"PRId32,op=='T'?(int32_t)small[i]:out[i]);
        putchar('\n');
    }
    return 0;
}
int main(int argc,char **argv)
{
    if(argc==2 && strcmp(argv[1],"--vectors")==0)return vectors();
    basic();roots();residuals();warm_allocations();
    printf("normalization-v1: %u checks, %u failures\n",checks,failures);
    return failures?1:0;
}
