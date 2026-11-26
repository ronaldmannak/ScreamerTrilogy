#ifndef PREVIEW_SOURCE_FILE
#error Define PREVIEW_SOURCE_FILE
#endif
#define main unused_preview_main
#include PREVIEW_SOURCE_FILE
#undef main
static void requireContract(bool value,const char *message){if(!value)throw std::runtime_error(message);}
template<class Block>static void mustReject(Block block){bool rejected=false;try{block();}catch(const std::exception &){rejected=true;}requireContract(rejected,"Malformed reflection contract was accepted");}
int main(){@autoreleasepool{try{
    NSDictionary *identity=@{@"model":@1,@"position":@[@0,@0,@0],@"rotation":@[@1,@0,@0,@0,@1,@0,@0,@0,@1]};
    NSMutableDictionary *input=[identity mutableCopy];input[@"reflection_phase"]=@32768;input[@"reflection_scroll"]=@[@.99609375,@0];
    Pose a=poseFromJSON(input);requireContract(a.reflectionPhase==32768,"Original phase was lost");
    auto b=a;b.reflectionScroll={0,0};auto forward=interpolatedReflectionScroll(a,b,.5f);requireContract(fabsf(forward.x-255.5f/256)<1e-7,"Scroll seam took the long direction");
    auto reverse=interpolatedReflectionScroll(b,a,.5f);requireContract(fabsf(reverse.x+.5f/256)<1e-7,"Reverse scroll seam took the long direction");
    input[@"reflection_phase"]=@65536;mustReject([&]{poseFromJSON(input);});input[@"reflection_phase"]=@1.5;mustReject([&]{poseFromJSON(input);});
    input[@"reflection_phase"]=@0;input[@"reflection_scroll"]=@[@1,@0];mustReject([&]{poseFromJSON(input);});
    Batch batch{};batch.texture=7;batch.s1Reflection=true;batch.reflectionTextures={7,11,19};
    for(auto pair:std::vector<std::pair<uint32_t,NSInteger>>{{0,7},{21845,7},{21846,11},{32768,11},{43690,11},{43691,19},{65280,19},{65535,19}})requireContract(reflectionTexture(batch,pair.first)==pair.second,"Original frame boundary mismatch");
    batch.s1Reflection=false;requireContract(reflectionTexture(batch,65280)==7,"Legacy material texture changed");
    mustReject([&]{reflectionTextures(@{@"reflection_textures":@[@0,@3]},3,0);});mustReject([&]{reflectionTextures(@{@"reflection_textures":@[@(-1)]},3,0);});
    auto legacy=sceneNormals(@{},@"/unused",3);requireContract(legacy.size()==9&&std::all_of(legacy.begin(),legacy.end(),[](float x){return x==0;}),"Legacy scenes no longer accept missing normal data");
    NSDictionary *glass=@{@"texgen":@"s1-reflection",@"source_material_type":@160,@"texture":@0,@"blend":@NO,@"alpha_test":@NO};requireContract(s1ReflectionBatch(glass,@{@"normals":@{}}),"Opaque A0 contract rejected");
    NSMutableDictionary *transparent=[glass mutableCopy];transparent[@"blend"]=@YES;mustReject([&]{s1ReflectionBatch(transparent,@{@"normals":@{}});});
    puts("Reflection pose, scroll, frame-boundary, malformed-data and legacy contracts passed");return 0;
}catch(const std::exception &e){fprintf(stderr,"%s\n",e.what());return 1;}}}
