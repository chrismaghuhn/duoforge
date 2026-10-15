#include "eval/arithmetic.h"
#include "eval/kernels.h"
#include "eval/inputs.h"
#include "encode/encode_internal.h"
#include "support/check.h"
#include <limits.h>
#include <stdio.h>
#include <string.h>
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

static FILE *open_oracle(const char *path)
{
#if defined(_MSC_VER)
    FILE *file = NULL;
    if (fopen_s(&file, path, "rb") != 0) return NULL;
    return file;
#else
    return fopen(path, "rb");
#endif
}

static uint64_t read64(const uint8_t *p) { uint64_t x=0; for(uint32_t i=0;i<8u;++i)x|=(uint64_t)p[i]<<(8u*i);return x; }
static void write64(uint8_t *p,uint64_t v) { for(uint32_t i=0;i<8u;++i)p[i]=(uint8_t)(v>>(8u*i)); }
static int64_t signed64(uint64_t v) { return v <= INT64_MAX ? (int64_t)v : -1 - (int64_t)(UINT64_MAX-v); }
/* Fixed byte framing deliberately avoids struct ABI/host-endian assumptions. */
static int oracle(const char *path)
{
    FILE *file=open_oracle(path); if(!file)return 2;
    uint8_t frame[64],result[12];
    while(fread(frame,1,sizeof(frame),file)==sizeof(frame)) {
        uint64_t a[8]; for(uint32_t i=0;i<8u;++i)a[i]=read64(frame+8u*i);
        int64_t q=0; int16_t q16=0; uint32_t id=0; duoforge_status st=DUOFORGE_E_INVALID_ARGUMENT;
        dfi_eval_scale scale={(uint32_t)a[2],(uint32_t)a[3]};
        switch(a[0]) {
        case 1:st=dfi_eval_add(signed64(a[1]),signed64(a[2]),&q);break;
        case 2:st=dfi_eval_mul(signed64(a[1]),signed64(a[2]),&q);break;
        case 3:st=dfi_eval_round_div(signed64(a[1]),a[2],&q);break;
        case 4:st=dfi_eval_requant(signed64(a[1]),scale,&q);break;
        case 5:st=dfi_eval_binary32((uint32_t)a[1],scale,&q16);q=q16;break;
        case 6:st=dfi_eval_binary32_id((uint32_t)a[1],(uint32_t)a[2],(uint32_t)a[3],&id);q=id;break;
        case 10: { int32_t q32=0;st=dfi_eval_requant32(signed64(a[1]),scale,&q32);q=q32;break; }
        case 7:st=dfi_eval_requant16(signed64(a[1]),scale,&q16);q=q16;break;
        case 8:
        case 11: {
            int16_t x[2]={(int16_t)signed64(a[1]),(int16_t)signed64(a[2])};
            int8_t w[2]={(int8_t)signed64(a[3]),(int8_t)signed64(a[4])};
            int64_t b=signed64(a[5]);dfi_eval_scale s={(uint32_t)a[6],(uint32_t)a[7]};
            if(a[0]==11u){int32_t q32=0;st=dfi_eval_dense32(x,2,w,&b,&s,1,false,&q32);q=q32;}
            else {st=dfi_eval_dense(x,2,w,&b,&s,1,false,&q16);q=q16;}break;
        }
        case 9: {
            int16_t x[3]={(int16_t)signed64(a[1]),(int16_t)signed64(a[2]),(int16_t)signed64(a[3])};
            uint8_t m[3]={(uint8_t)(a[4]&1u),(uint8_t)((a[4]>>1)&1u),(uint8_t)((a[4]>>2)&1u)};
            dfi_eval_scale s={(uint32_t)a[6],(uint32_t)a[7]};
            st=dfi_eval_pool(x,m,3,1,a[5]!=0,s,&q16);q=q16;break;
        }
        case 12: {
            uint64_t bound=0;
            st=dfi_eval_dot_bound((uint32_t)a[1],(uint32_t)a[2],(uint32_t)a[3],a[4],
                (dfi_eval_scale){(uint32_t)a[5],(uint32_t)a[6]},&bound);
            if(st==DUOFORGE_OK)q=(int64_t)bound;
            break;
        }
        default:break;
        }
        if(st!=DUOFORGE_OK)q=0;
        for(uint32_t i=0;i<4u;++i)result[i]=(uint8_t)(st>>(8u*i));
        write64(result+4,(uint64_t)q);
        if(fwrite(result,1,sizeof(result),stdout)!=sizeof(result)){fclose(file);return 3;}
    }
    int failed=ferror(file); fclose(file); return failed?4:0;
}
static int input_oracle(const char *path)
{
    FILE *file = open_oracle(path); if (!file) return 2;
    uint8_t header[28], raw[1094u * 4u];
    if (fread(header, 1, sizeof(header), file) != sizeof(header)) { fclose(file); return 3; }
    uint32_t h[7];
    for (uint32_t i = 0; i < 7u; ++i) {
        h[i] = 0; for (uint32_t j = 0; j < 4u; ++j) h[i] |= (uint32_t)header[4u*i+j] << (8u*j);
    }
    const dfi_eval_id_capacities cap = {h[2], h[3], h[4], h[5], h[6]};
    dfi_eval_scale scales[1094];for(uint32_t i=0;i<1094u;++i)scales[i]=(dfi_eval_scale){h[0],h[1]};
    while (fread(raw, 1, sizeof(raw), file) == sizeof(raw)) {
        uint32_t bits[1094];dfi_eval_inputs out; char reason[128];uint8_t result[4 + 2u*1094u + 4u*96u + 28u];
        for (uint32_t i = 0; i < 1094u; ++i) {
            bits[i] = 0; for (uint32_t j = 0; j < 4u; ++j) bits[i] |= (uint32_t)raw[4u*i+j] << (8u*j);
        }
        duoforge_status st=dfi_eval_prepare_inputs(bits,scales,cap,&out,reason);
        memset(result,0,sizeof(result));for(uint32_t i=0;i<4u;++i)result[i]=(uint8_t)(st>>(8u*i));
        uint32_t pos=4;
        if (st == DUOFORGE_OK) {
            for(uint32_t i=0;i<1094u;++i){uint16_t q=(uint16_t)out.scalars[i];result[pos++]=(uint8_t)q;result[pos++]=(uint8_t)(q>>8u);}
            for(uint32_t field=0;field<5u;++field) for(uint32_t side=0;side<2u;++side) for(uint32_t m=0;m<6u;++m) {
                uint32_t count = field == 4u ? 4u : 1u;
                for(uint32_t k=0;k<count;++k){
                    uint32_t id=field==0u?out.species[side][m]:field==1u?out.item[side][m]:field==2u?out.ability[side][m]:field==3u?out.nature[side][m]:out.moves[side][m][k];
                    for(uint32_t j=0;j<4u;++j)result[pos++]=(uint8_t)(id>>(8u*j));
                }
            }
            for(uint32_t side=0;side<2u;++side)for(uint32_t m=0;m<6u;++m)result[pos++]=out.registered[side][m];
            for(uint32_t side=0;side<2u;++side)for(uint32_t m=0;m<6u;++m)result[pos++]=out.move_count[side][m];
            for(uint32_t side=0;side<2u;++side)for(uint32_t p=0;p<2u;++p)result[pos++]=out.occupant[side][p];
        }
        if(fwrite(result,1,sizeof(result),stdout)!=sizeof(result)){fclose(file);return 4;}
    }
    int failed=ferror(file);fclose(file);return failed?5:0;
}
static void kernels(df_test *t)
{
    const int16_t x[3]={-32768,123,32767};
    const int8_t w[6]={-128,2,127,0,0,0};
    const int64_t b[2]={3,-5}; const dfi_eval_scale s[2]={{1,8},{1,1}};
    int16_t out[8]; memset(out,0xa5,sizeof(out));
    DF_CHECK(t,dfi_eval_dense(x,3,w,b,s,2,false,out)==DUOFORGE_OK);
    DF_CHECK(t,out[0]==32640 && out[1]==-2); DF_CHECK(t,out[2]==(int16_t)-23131);
    DF_CHECK(t,dfi_eval_dense(x,3,w,b,s,2,true,out)==DUOFORGE_OK&&out[1]==0);
    const int64_t badbias[2]={INT64_MAX,0};
    DF_CHECK(t,dfi_eval_dense(x,3,w,badbias,s,2,false,out)==DUOFORGE_E_EXHAUSTED);
    const dfi_eval_scale badscale[2]={{0,1},{1,0}};
    DF_CHECK(t,dfi_eval_dense(x,3,w,b,badscale,2,false,out)==DUOFORGE_E_INVALID_ARGUMENT);
    const int8_t table[6]={-128,0,127,2,-3,5};
    DF_CHECK(t,dfi_eval_embedding(table,2,3,0,(dfi_eval_scale){3,1},out)==DUOFORGE_OK);
    DF_CHECK(t,out[0]==-192&&out[1]==0&&out[2]==190);
    DF_CHECK(t,dfi_eval_embedding(table,2,3,2,(dfi_eval_scale){1,0},out)==DUOFORGE_E_UNSUPPORTED);
    const int16_t pool[6]={-8,-4,-2,-6,100,200}; const uint8_t mask[3]={1,1,0},none[3]={0,0,0},badmask[3]={0,2,0};
    DF_CHECK(t,dfi_eval_pool(pool,mask,3,2,false,(dfi_eval_scale){1,1},out)==DUOFORGE_OK&&out[0]==-5&&out[1]==-5);
    DF_CHECK(t,dfi_eval_pool(pool,mask,3,2,true,(dfi_eval_scale){1,0},out)==DUOFORGE_OK&&out[0]==-2&&out[1]==-4);
    DF_CHECK(t,dfi_eval_pool(pool,none,3,2,true,(dfi_eval_scale){1,0},out)==DUOFORGE_OK&&out[0]==0&&out[1]==0);
    DF_CHECK(t,dfi_eval_pool(NULL,NULL,0,2,false,(dfi_eval_scale){1,0},out)==DUOFORGE_OK&&out[0]==0);
    DF_CHECK(t,dfi_eval_pool(pool,badmask,3,2,false,(dfi_eval_scale){1,0},out)==DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t,dfi_eval_gather(pool,3,2,2,true,out)==DUOFORGE_OK&&out[0]==100&&out[1]==200);
    DF_CHECK(t,dfi_eval_gather(pool,3,2,UINT32_MAX,false,out)==DUOFORGE_OK&&out[0]==0&&out[1]==0);
    DF_CHECK(t,dfi_eval_gather(pool,3,2,3,true,out)==DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t,dfi_eval_concat(x,2,(dfi_eval_scale){1,1},x+2,1,(dfi_eval_scale){2,0},3,out)==DUOFORGE_OK);
    DF_CHECK(t,out[0]==-16384&&out[1]==62&&out[2]==32767);
    DF_CHECK(t,dfi_eval_concat(x,2,(dfi_eval_scale){1,0},x,1,(dfi_eval_scale){1,0},2,out)==DUOFORGE_E_CAPACITY);
    DF_CHECK(t,dfi_eval_dense(NULL,0,w,b,s,2,false,out)==DUOFORGE_E_NULL_ARGUMENT);
    int32_t out32[2];
    DF_CHECK(t,dfi_eval_dense32(x,3,w,b,s,2,false,out32)==DUOFORGE_OK&&out32[0]==32640&&out32[1]==-2);
    const int16_t headin[2]={32767,32767};const int8_t headw[2]={1,1};
    int64_t headbias=0;const dfi_eval_scale heads={1,0};
    DF_CHECK(t,dfi_eval_dense32(headin,2,headw,&headbias,&heads,1,false,out32)==DUOFORGE_OK&&out32[0]==65534);
    headbias=(int64_t)INT32_MAX-65534;
    DF_CHECK(t,dfi_eval_dense32(headin,2,headw,&headbias,&heads,1,false,out32)==DUOFORGE_OK&&out32[0]==INT32_MAX);
    ++headbias;DF_CHECK(t,dfi_eval_dense32(headin,2,headw,&headbias,&heads,1,false,out32)==DUOFORGE_E_EXHAUSTED);
    headbias=(int64_t)INT32_MIN-65534;
    DF_CHECK(t,dfi_eval_dense32(headin,2,headw,&headbias,&heads,1,false,out32)==DUOFORGE_OK&&out32[0]==INT32_MIN);
    --headbias;DF_CHECK(t,dfi_eval_dense32(headin,2,headw,&headbias,&heads,1,false,out32)==DUOFORGE_E_EXHAUSTED);
    headbias=-65534+INT64_C(3145728);
    DF_CHECK(t,dfi_eval_dense32(headin,2,headw,&headbias,&heads,1,false,out32)==DUOFORGE_OK&&out32[0]==3145728);
    int64_t q=0;uint64_t bound=0;
    DF_CHECK(t,dfi_eval_add(INT64_MAX,1,&q)==DUOFORGE_E_EXHAUSTED);
    DF_CHECK(t,dfi_eval_add(INT64_MIN,-1,&q)==DUOFORGE_E_EXHAUSTED);
    DF_CHECK(t,dfi_eval_mul(INT64_MIN,-1,&q)==DUOFORGE_E_EXHAUSTED);
    DF_CHECK(t,dfi_eval_mul(INT64_MIN,1,&q)==DUOFORGE_OK&&q==INT64_MIN);
    DF_CHECK(t,dfi_eval_round_div(-5,2,&q)==DUOFORGE_OK&&q==-2);
    DF_CHECK(t,dfi_eval_round_div(-3,2,&q)==DUOFORGE_OK&&q==-2);
    DF_CHECK(t,dfi_eval_round_div(INT64_MIN,UINT64_MAX,&q)==DUOFORGE_OK&&q==-1);
    DF_CHECK(t,dfi_eval_requant(INT64_MIN,(dfi_eval_scale){1,63},&q)==DUOFORGE_OK&&q==-1);
    DF_CHECK(t,dfi_eval_dot_bound(640,32768,128,1024,(dfi_eval_scale){2,16},&bound)==DUOFORGE_OK);
    DF_CHECK_EQ_U64(t,bound,UINT64_C(2684355584));
    DF_CHECK(t,dfi_eval_dot_bound(UINT32_MAX,32768,128,INT64_MAX,(dfi_eval_scale){1,0},&bound)==DUOFORGE_E_EXHAUSTED);
    DF_CHECK(t,dfi_eval_dot_bound(0,0,0,0,(dfi_eval_scale){UINT32_MAX,0},&bound)==DUOFORGE_OK&&bound==0);
    bound=123;
    DF_CHECK(t,dfi_eval_dot_bound(0,0,0,0,(dfi_eval_scale){0,0},&bound)==DUOFORGE_E_INVALID_ARGUMENT&&bound==123);
    DF_CHECK(t,dfi_eval_dot_bound(0,0,0,INT64_MAX,(dfi_eval_scale){1,0},&bound)==DUOFORGE_OK&&bound==(uint64_t)INT64_MAX);
    bound=123;
    DF_CHECK(t,dfi_eval_dot_bound(0,0,0,INT64_MAX,(dfi_eval_scale){2,0},&bound)==DUOFORGE_E_EXHAUSTED&&bound==123);
    DF_CHECK(t,dfi_eval_dot_bound(0,0,0,(uint64_t)INT64_MAX/2u,(dfi_eval_scale){2,0},&bound)==DUOFORGE_OK&&bound==(uint64_t)INT64_MAX/2u);
    bound=123;
    DF_CHECK(t,dfi_eval_dot_bound(0,0,0,(uint64_t)INT64_MAX/2u+1u,(dfi_eval_scale){2,0},&bound)==DUOFORGE_E_EXHAUSTED&&bound==123);
    DF_CHECK(t,dfi_eval_dot_bound(0,0,0,(uint64_t)INT64_MAX/UINT32_MAX,(dfi_eval_scale){UINT32_MAX,0},&bound)==DUOFORGE_OK&&bound==(uint64_t)INT64_MAX/UINT32_MAX);
    bound=123;
    DF_CHECK(t,dfi_eval_dot_bound(0,0,0,(uint64_t)INT64_MAX/UINT32_MAX+1u,(dfi_eval_scale){UINT32_MAX,0},&bound)==DUOFORGE_E_EXHAUSTED&&bound==123);
}
static void extents(df_test *t)
{
    /* Same pure helper used by every typed preflight; a supplied limit tests
       32-bit boundaries on all CI hosts without overriding production SIZE_MAX. */
    const size_t bound32 = UINT32_MAX;
    DF_CHECK(t,dfi_eval_extent(1,UINT32_MAX,1,bound32));
    DF_CHECK(t,!dfi_eval_extent(1,UINT32_MAX,2,bound32));
    DF_CHECK(t,!dfi_eval_extent(1,UINT32_MAX,4,bound32));
    DF_CHECK(t,!dfi_eval_extent(1,UINT32_MAX,8,bound32));
    DF_CHECK(t,dfi_eval_extent(0,UINT32_MAX,2,bound32));
    DF_CHECK(t,!dfi_eval_extent(1,1,0,bound32));
    DF_CHECK(t,dfi_eval_extent(2,10,2,40));
    DF_CHECK(t,!dfi_eval_extent(2,10,2,39));
    DF_CHECK(t,dfi_eval_extent(1,0,8,0));
    DF_CHECK(t,!dfi_eval_extent(UINT32_MAX,UINT32_MAX,2,SIZE_MAX));
#if SIZE_MAX == UINT32_MAX
    /* One-cell backing buffers: an attempted loop is an immediate out-of-bounds
       read/write under ASan. Every impossible extent must refuse untouched. */
    const int16_t in = 1;const int8_t weight = 1;const int64_t bias = 0;
    const dfi_eval_scale scale = {1,0};const uint8_t mask = 1;
    int16_t out16 = -23131;int32_t out32 = INT32_C(-1515870811);
    DF_CHECK(t,dfi_eval_dense(&in,UINT32_MAX,&weight,&bias,&scale,1,false,&out16)==DUOFORGE_E_CAPACITY);
    DF_CHECK(t,dfi_eval_dense(&in,1,&weight,&bias,&scale,UINT32_MAX,false,&out16)==DUOFORGE_E_CAPACITY);
    DF_CHECK(t,dfi_eval_dense32(&in,1,&weight,&bias,&scale,UINT32_MAX,false,&out32)==DUOFORGE_E_CAPACITY);
    DF_CHECK(t,dfi_eval_embedding(&weight,1,UINT32_MAX,0,scale,&out16)==DUOFORGE_E_CAPACITY);
    DF_CHECK(t,dfi_eval_pool(&in,&mask,1,UINT32_MAX,false,scale,&out16)==DUOFORGE_E_CAPACITY);
    DF_CHECK(t,dfi_eval_pool(NULL,NULL,0,UINT32_MAX,true,scale,&out16)==DUOFORGE_E_CAPACITY);
    DF_CHECK(t,dfi_eval_gather(&in,0,UINT32_MAX,UINT32_MAX,false,&out16)==DUOFORGE_E_CAPACITY);
    DF_CHECK(t,dfi_eval_concat(&in,UINT32_MAX,scale,&in,0,scale,UINT32_MAX,&out16)==DUOFORGE_E_CAPACITY);
    DF_CHECK(t,dfi_eval_concat(&in,0,scale,&in,0,scale,UINT32_MAX,&out16)==DUOFORGE_E_CAPACITY);
    DF_CHECK(t,out16==-23131&&out32==INT32_C(-1515870811));
#endif
}
static void inputs(df_test *t)
{
    const dfi_eval_column *cols=dfi_eval_input_columns();
    const char *names[1094];uint32_t bits[1094]={0}; dfi_eval_scale scales[1094];
    uint32_t counts[13]={0};uint32_t species=0,present=0,count=0,scalar=0,occupant=0;
    for(uint32_t i=0;i<1094u;++i) {
        names[i]=cols[i].name;scales[i]=(dfi_eval_scale){1024,0};++counts[cols[i].group];
        if(cols[i].group==DFI_EVAL_GROUP_OCCUPANT&&cols[i].c==6u)bits[i]=UINT32_C(0x3f800000);
        if(cols[i].group==DFI_EVAL_GROUP_SPECIES&&cols[i].a==0u&&cols[i].b==0u)species=i;
        if(cols[i].group==DFI_EVAL_GROUP_PRESENT&&cols[i].a==0u&&cols[i].b==0u)present=i;
        if(cols[i].group==DFI_EVAL_GROUP_MOVE_COUNT&&cols[i].a==0u&&cols[i].b==0u)count=i;
        if(cols[i].group==DFI_EVAL_GROUP_MEMBER)scalar=i;
        if(cols[i].group==DFI_EVAL_GROUP_OCCUPANT&&cols[i].a==0u&&cols[i].b==0u&&cols[i].c==6u)occupant=i;
    }
    DF_CHECK_EQ_U64(t,counts[DFI_EVAL_GROUP_GLOB],36);DF_CHECK_EQ_U64(t,counts[DFI_EVAL_GROUP_SIDE],58);
    DF_CHECK_EQ_U64(t,counts[DFI_EVAL_GROUP_POSITION],420);DF_CHECK_EQ_U64(t,counts[DFI_EVAL_GROUP_MEMBER],384);
    DF_CHECK_EQ_U64(t,counts[DFI_EVAL_GROUP_OCCUPANT],28);
    char reason[128];dfi_eval_inputs out; dfi_eval_id_capacities cap={65536,65536,256,256,25};
    DF_CHECK(t,dfi_eval_input_schema(names,1094,reason)==DUOFORGE_OK&&reason[0]==0);
    DF_CHECK(t,dfi_eval_input_schema(names,1093,reason)==DUOFORGE_E_UNSUPPORTED&&strstr(reason,"missing"));
    names[1]=names[0];DF_CHECK(t,dfi_eval_input_schema(names,1094,reason)==DUOFORGE_E_INVALID_ARGUMENT&&strstr(reason,"duplicate"));
    names[1]="unknown.column";DF_CHECK(t,dfi_eval_input_schema(names,1094,reason)==DUOFORGE_E_UNSUPPORTED&&strstr(reason,"unknown.column"));
    names[1]=NULL;DF_CHECK(t,dfi_eval_input_schema(names,1094,reason)==DUOFORGE_E_INVALID_ARGUMENT&&strstr(reason,"malformed"));
    DF_CHECK(t,dfi_eval_prepare_inputs(bits,scales,cap,&out,reason)==DUOFORGE_OK);
    DF_CHECK(t,out.occupant[0][0]==6&&out.registered[0][0]==0);
    bits[present]=UINT32_C(0x3f800000);bits[count]=UINT32_C(0x3e800000);
    /* Species zero is valid; registration derives from move_count, not species. */
    DF_CHECK(t,dfi_eval_prepare_inputs(bits,scales,cap,&out,reason)==DUOFORGE_OK&&out.registered[0][0]==1&&out.species[0][0]==0);
    scales[species]=(dfi_eval_scale){0,99};
    bits[species]=UINT32_C(0x3f800000);
    DF_CHECK(t,dfi_eval_prepare_inputs(bits,scales,cap,&out,reason)==DUOFORGE_OK&&out.species[0][0]==65535&&out.scalars[species]==0);
    cap.species=65535;DF_CHECK(t,dfi_eval_prepare_inputs(bits,scales,cap,&out,reason)==DUOFORGE_E_UNSUPPORTED&&strstr(reason,"species"));cap.species=65536;
    bits[scalar]=UINT32_C(0x3f000000);
    DF_CHECK(t,dfi_eval_prepare_inputs(bits,scales,cap,&out,reason)==DUOFORGE_OK&&out.scalars[scalar]==512);
    bits[scalar]=UINT32_C(0x7fc00000);DF_CHECK(t,dfi_eval_prepare_inputs(bits,scales,cap,&out,reason)==DUOFORGE_E_INVALID_ARGUMENT&&strstr(reason,"scalar"));bits[scalar]=0;
    bits[count]=UINT32_C(0x3e900000);DF_CHECK(t,dfi_eval_prepare_inputs(bits,scales,cap,&out,reason)==DUOFORGE_E_INVALID_ARGUMENT&&strstr(reason,"move_count"));bits[count]=UINT32_C(0x3e800000);
    bits[occupant]=0;DF_CHECK(t,dfi_eval_prepare_inputs(bits,scales,cap,&out,reason)==DUOFORGE_E_INVALID_ARGUMENT&&strstr(reason,"occupant"));bits[occupant]=UINT32_C(0x3f800000);
    uint32_t copied[1094];dfi_encoder_input_bits(bits,copied);DF_CHECK_BYTES(t,(uint8_t*)bits,(uint8_t*)copied,sizeof(bits),"encoder bit bridge");
    DF_CHECK(t,sizeof(out)<4096u);
}
int main(int argc,char **argv)
{
    if(argc==3&&strcmp(argv[1],"--inputs")==0)return input_oracle(argv[2]);
    if(argc==2)return oracle(argv[1]);
    df_test t;df_test_begin(&t,"eval.kernels");
#ifdef DF_EVAL_ALLOC_HOOKS
    allocation_watch=true;
#endif
    kernels(&t);extents(&t);inputs(&t);
#ifdef DF_EVAL_ALLOC_HOOKS
    allocation_watch=false;DF_CHECK_EQ_U64(&t,allocations,0);
#endif
    return df_test_end(&t);
}
