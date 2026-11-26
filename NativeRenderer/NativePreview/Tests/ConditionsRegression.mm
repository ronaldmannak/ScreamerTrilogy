// SPDX-License-Identifier: GPL-3.0-only
// Actual production shader probes using authored vertices and one-pixel colors.
#ifndef PREVIEW_SOURCE_FILE
#error Define PREVIEW_SOURCE_FILE as the production NativePreview.mm path
#endif
#define main includedProductionMain
#include PREVIEW_SOURCE_FILE
#undef main
#include <array>
#include <limits>

struct Pixel { uint8_t r,g,b,a; };
static NSArray *components(Pixel p){return @[@(p.r),@(p.g),@(p.b),@(p.a)];}
static void requireTest(bool condition,const char *message){if(!condition)throw std::runtime_error(message);}
static bool same(Pixel a,Pixel b){return a.r==b.r&&a.g==b.g&&a.b==b.b&&a.a==b.a;}
static double separation(Pixel a,Pixel b){return sqrt(pow((double)a.r-b.r,2)+pow((double)a.g-b.g,2)+pow((double)a.b-b.b,2));}
static bool close2(simd::float2 a,simd::float2 b){return simd_length(a-b)<1e-5f;}

static void checkTransitions(){
    using Conditions::Preset;Conditions::Transition state;
    requireTest(state.target==Preset::Day&&close2(state.sample(0),(simd::float2){0,0}),"Default conditions must be Day");
    Preset parsed=Preset::Night;
    requireTest(Conditions::fromString("day",parsed)&&parsed==Preset::Day,"CLI day preset not recognized");
    requireTest(Conditions::fromString("NIGHT",parsed)&&parsed==Preset::Night,"CLI night preset not recognized");
    requireTest(Conditions::fromString("fog",parsed)&&parsed==Preset::Fog,"CLI fog preset not recognized");
    requireTest(!Conditions::fromString("rain",parsed)&&parsed==Preset::Fog,"Unknown conditions must fail without changing output");
    state.select(Preset::Night,10);
    requireTest(close2(state.sample(10),(simd::float2){0,0}),"A transition jumped at its start");
    simd::float2 half=state.sample(10.3);
    requireTest(half.x>.4f&&half.x<.6f&&half.y==0,"Night must blend smoothly midway");
    requireTest(close2(state.sample(10.6),(simd::float2){1,0}),"Night transition did not finish");
    state.select(Preset::Fog,10.3);
    requireTest(close2(state.sample(10.3),half),"Interrupted transition changed its current appearance");
    simd::float2 blend=state.sample(10.6);
    requireTest(blend.x>0&&blend.y>0&&blend.x+blend.y<=1.00001f,"Interrupted preset blend is invalid");
    requireTest(close2(state.sample(10.9),(simd::float2){0,1}),"Fog transition did not finish");
    state.select(Preset::Day,11);
    requireTest(close2(state.sample(11.6),(simd::float2){0,0}),"Returning to Day must restore original colors");
    for(auto preset:{Preset::Day,Preset::Night,Preset::Fog}){
        state.setImmediate(preset);simd::float2 values=state.sample(0);
        requireTest(std::isfinite(values.x)&&std::isfinite(values.y),"Immediate preset is not finite");
    }
    for(float distance:{-1.f,0.f,std::numeric_limits<float>::infinity(),std::numeric_limits<float>::quiet_NaN(),1000.f}){
        ConditionsUniforms value=Conditions::makeUniforms((simd::float2){.8f,.8f},distance);
        for(int i=0;i<4;i++)requireTest(std::isfinite(value.weights[i])&&std::isfinite(value.fogColor[i]),"Uniform sanitization emitted nonfinite values");
        requireTest(value.weights.x>=0&&value.weights.y>=0&&value.weights.x+value.weights.y<=1.00001f&&value.weights.w>0,"Condition uniforms exceed supported range");
    }
}
static void checkAssetVariants(){
    NSDictionary *entry=@{@"available":@YES,@"world_scene":@"night/world.json",@"cars_scene":@"night/cars.json",@"sky_texture":@"night/sky.png",@"sky":@{@"enabled":@YES,@"ground_rgb":@[@0,@0,@0],@"flat_rgb":@[@0,@0,@0]},@"night_fog":@{@"enabled":@NO,@"near":@6000,@"far":@35000}};
    NSMutableDictionary *input=[@{@"schema":@"screamer-live/v1",@"epoch":@"source-physics",@"seq":@42,@"sample_monotonic_ns":@1000000000,@"physics_period_ms":@30,@"assets":@{@"epoch":@"immutable-capture",@"world_scene":@"day/world.json",@"cars_scene":@"day/cars.json",@"condition_variants":@{@"schema":@"screamer-original-conditions/v1",@"original":@"day",@"night":entry}}} mutableCopy];
    LiveFrame base=liveFrameFromJSON(input,@"/tmp/conditions-test"),night=frameWithOriginalNight(base,true),day=frameWithOriginalNight(base,false);
    requireTest(base.night.known&&base.night.available&&!base.night.fogEnabled,"Original night availability/fog contract failed");
    requireTest(night.worldScene=="/tmp/conditions-test/night/world.json"&&night.carsScene=="/tmp/conditions-test/night/cars.json"&&[night.skyPath isEqual:@"/tmp/conditions-test/night/sky.png"],"Night did not select a complete authored asset set");
    requireTest(day.worldScene==base.worldScene&&day.carsScene==base.carsScene,"Day did not restore original scene assets");
    requireTest(night.seq==base.seq&&night.sampleAt==base.sampleAt&&night.period==base.period&&night.epoch==base.epoch&&night.assetsEpoch==base.assetsEpoch,"Selecting visual variants altered the source simulation identity or clock");
    input[@"assets"]=@{@"world_scene":@"day/world.json",@"condition_variants":@{@"schema":@"screamer-original-conditions/v1",@"original":@"night",@"night":@{@"available":@NO,@"reason":@"No authored night bank"}}};
    base=liveFrameFromJSON(input,@"/tmp/conditions-test");
    requireTest(base.night.known&&!base.night.available&&base.night.originalNight&&frameWithOriginalNight(base,true).worldScene==base.worldScene,"Missing original night bank was not safely rejected");
    bool rejected=false;input[@"assets"]=@{@"condition_variants":@{@"schema":@"screamer-original-conditions/v1",@"night":@{@"available":@YES}}};
    try{liveFrameFromJSON(input,@"/tmp/conditions-test");}catch(const std::exception &){rejected=true;}
    requireTest(rejected,"Incomplete night asset set must not reach the renderer");
}

@interface ConditionsProbe : NSObject
@property(strong)id<MTLDevice> device;
@property(strong)id<MTLCommandQueue> queue;
@property(strong)id<MTLLibrary> library;
@property(strong)id<MTLSamplerState> sampler;
@property(assign)NSInteger blendMode;
- (instancetype)initWithShader:(NSString *)shader;
- (Pixel)render:(NSString *)fragment conditions:(ConditionsUniforms)conditions distance:(float)distance color:(Pixel)color cutoff:(float)cutoff sourceAlpha:(BOOL)sourceAlpha;
@end
@implementation ConditionsProbe
- (instancetype)initWithShader:(NSString *)shader {
    self=[super init];if(!self)return nil;
    self.device=MTLCreateSystemDefaultDevice();requireTest(self.device!=nil,"No Metal device for conditions regression");
    self.queue=[self.device newCommandQueue];NSError *error=nil;
    NSString *source=[NSString stringWithContentsOfFile:shader encoding:NSUTF8StringEncoding error:&error];
    self.library=source?[self.device newLibraryWithSource:source options:nil error:&error]:nil;
    if(!self.library)throw std::runtime_error(error.localizedDescription.UTF8String);
    MTLSamplerDescriptor *sampling=[MTLSamplerDescriptor new];sampling.minFilter=MTLSamplerMinMagFilterNearest;sampling.magFilter=MTLSamplerMinMagFilterNearest;
    self.sampler=[self.device newSamplerStateWithDescriptor:sampling];return self;
}
- (Pixel)render:(NSString *)fragment conditions:(ConditionsUniforms)conditions distance:(float)distance color:(Pixel)color cutoff:(float)cutoff sourceAlpha:(BOOL)sourceAlpha {
    BOOL world=[fragment isEqual:@"worldFragment"];
    MTLRenderPipelineDescriptor *descriptor=[MTLRenderPipelineDescriptor new];
    descriptor.vertexFunction=[self.library newFunctionWithName:world?@"worldVertex":@"framebufferVertex"];
    descriptor.fragmentFunction=[self.library newFunctionWithName:fragment];descriptor.colorAttachments[0].pixelFormat=MTLPixelFormatBGRA8Unorm;
    configureBlend(descriptor.colorAttachments[0],static_cast<BlendMode>(self.blendMode));
    if(world){
        MTLVertexDescriptor *layout=[MTLVertexDescriptor vertexDescriptor];
        layout.attributes[0].format=MTLVertexFormatFloat3;layout.attributes[0].offset=0;layout.attributes[0].bufferIndex=0;
        layout.attributes[1].format=MTLVertexFormatFloat2;layout.attributes[1].offset=12;layout.attributes[1].bufferIndex=0;
        layout.attributes[2].format=MTLVertexFormatFloat4;layout.attributes[2].offset=20;layout.attributes[2].bufferIndex=0;
        layout.attributes[3].format=MTLVertexFormatFloat3;layout.attributes[3].offset=0;layout.attributes[3].bufferIndex=2;
        layout.layouts[0].stride=sizeof(Vertex);layout.layouts[2].stride=12;descriptor.vertexDescriptor=layout;
    }
    NSError *error=nil;id<MTLRenderPipelineState> pipeline=[self.device newRenderPipelineStateWithDescriptor:descriptor error:&error];
    if(!pipeline)throw std::runtime_error(error.localizedDescription.UTF8String);
    auto td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:1 height:1 mipmapped:NO];td.storageMode=MTLStorageModeShared;
    id<MTLTexture> texture=[self.device newTextureWithDescriptor:td];
    [texture replaceRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0 withBytes:&color bytesPerRow:4];
    auto targetDescriptor=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:32 height:32 mipmapped:NO];
    targetDescriptor.storageMode=MTLStorageModeShared;targetDescriptor.usage=MTLTextureUsageRenderTarget;
    id<MTLTexture> target=[self.device newTextureWithDescriptor:targetDescriptor];
    MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
    pass.colorAttachments[0].texture=target;pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;
    pass.colorAttachments[0].clearColor=MTLClearColorMake(13./255,17./255,23./255,1);
    Uniforms uniforms={};uniforms.matrix=matrix_identity_float4x4;uniforms.matrix.columns[2]=(simd::float4){0,0,0,0};uniforms.matrix.columns[3].z=.5f;
    uniforms.model=matrix_identity_float4x4;uniforms.reflectionWorldToView=matrix_identity_float4x4;uniforms.options=(simd::float4){1,cutoff,sourceAlpha?1.f:0.f,0};uniforms.conditions=conditions;
    if(self.blendMode)uniforms.options.z=self.blendMode;
    id<MTLCommandBuffer> command=[self.queue commandBuffer];id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];
    [encoder setRenderPipelineState:pipeline];[encoder setCullMode:MTLCullModeNone];
    [encoder setFragmentTexture:texture atIndex:0];[encoder setFragmentSamplerState:self.sampler atIndex:0];
    [encoder setFragmentBytes:&uniforms length:sizeof(uniforms) atIndex:1];
    if(world){
        const Vertex vertices[6]={{-1,-1,-distance,0,0,1,1,1,1},{1,-1,-distance,0,0,1,1,1,1},{-1,1,-distance,0,0,1,1,1,1},
                                  {-1,1,-distance,0,0,1,1,1,1},{1,-1,-distance,0,0,1,1,1,1},{1,1,-distance,0,0,1,1,1,1}};
        const float normals[18]={};[encoder setVertexBytes:vertices length:sizeof(vertices) atIndex:0];[encoder setVertexBytes:normals length:sizeof(normals) atIndex:2];
        [encoder setVertexBytes:&uniforms length:sizeof(uniforms) atIndex:1];
    }else{
        FramebufferUniforms rectangle{(simd::float4){0,0,1,1},(simd::float4){0,0,1,1}};
        simd::float4 originalSky={0,0,0,-1};[encoder setVertexBytes:&rectangle length:sizeof(rectangle) atIndex:0];
        [encoder setFragmentBytes:&originalSky length:sizeof(originalSky) atIndex:0];
    }
    [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:6];[encoder endEncoding];[command commit];[command waitUntilCompleted];
    if(command.status!=MTLCommandBufferStatusCompleted)throw std::runtime_error(command.error.localizedDescription.UTF8String);
    uint8_t bytes[4];[target getBytes:bytes bytesPerRow:4 fromRegion:MTLRegionMake2D(16,16,1,1) mipmapLevel:0];
    return Pixel{bytes[2],bytes[1],bytes[0],bytes[3]};
}
@end

int main(int argc,const char **argv){@autoreleasepool{try{
    requireTest(argc==3,"Usage: ConditionsRegression World.metal report.json");checkTransitions();checkAssetVariants();
    ConditionsProbe *probe=[[ConditionsProbe alloc]initWithShader:[NSString stringWithUTF8String:argv[1]]];
    auto day=Conditions::makeUniforms((simd::float2){0,0},1000),night=Conditions::makeUniforms((simd::float2){1,0},1000),fog=Conditions::makeUniforms((simd::float2){0,1},1000);
    Pixel source{64,96,160,255};NSMutableArray *checks=[NSMutableArray array];
    auto world=[&](ConditionsUniforms conditions,float distance,Pixel pixel=Pixel{64,96,160,255},float cutoff=0.f,BOOL alpha=NO){return [probe render:@"worldFragment" conditions:conditions distance:distance color:pixel cutoff:cutoff sourceAlpha:alpha];};
    Pixel original=world(day,200),nightWorld=world(night,200),nearFog=world(fog,20),middleFog=world(fog,200),farFog=world(fog,1000);
    requireTest(same(original,source)&&same(world(day,1000),source),"Day changed the original sampled world color");
    requireTest(same(nightWorld,source),"Night recolored authored near-field artwork");
    requireTest(same(world(night,40000),Pixel{0,0,0,255}),"Original night distance haze did not reach black");
    Pixel fogColor{(uint8_t)lround(fog.fogColor.x*255),(uint8_t)lround(fog.fogColor.y*255),(uint8_t)lround(fog.fogColor.z*255),255};
    requireTest(same(nearFog,original),"Fog hid the near-field race view");
    requireTest(separation(middleFog,fogColor)<separation(nearFog,fogColor)&&separation(farFog,fogColor)<separation(middleFog,fogColor),"Fog did not increase monotonically with geometry distance");
    requireTest(separation(farFog,fogColor)<=2,"Distant geometry did not converge to the fog sky color");
    [checks addObject:@{@"check":@"world_day_night_distance_fog",@"day":components(original),@"night":components(nightWorld),@"fog_near":components(nearFog),@"fog_mid":components(middleFog),@"fog_far":components(farFog)}];
    Pixel keyed{200,80,40,0},clear{13,17,23,255};
    for(auto conditions:{day,night,fog}){
        requireTest(same(world(conditions,1000,keyed,.5f),clear),"Conditions filled an alpha-key hole");
        Pixel partial=world(conditions,200,Pixel{64,96,160,64},0,YES);requireTest(partial.a==64,"Conditions changed original source alpha");
    }
    [checks addObject:@{@"check":@"alpha_key_discard_and_source_alpha",@"passed":@YES}];
    Pixel skySource{80,120,200,255};
    Pixel daySky=[probe render:@"backgroundFragment" conditions:day distance:0 color:skySource cutoff:0 sourceAlpha:NO];
    Pixel nightSky=[probe render:@"backgroundFragment" conditions:night distance:0 color:skySource cutoff:0 sourceAlpha:NO];
    Pixel fogSky=[probe render:@"backgroundFragment" conditions:fog distance:0 color:skySource cutoff:0 sourceAlpha:NO];
    requireTest(same(daySky,skySource),"Day changed the original sampled sky");
    requireTest(same(nightSky,skySource),"Night recolored the authored sky texture");
    requireTest(separation(fogSky,fogColor)<=2,"Fog sky and distant world colors differ");
    [checks addObject:@{@"check":@"sky_day_night_fog",@"day":components(daySky),@"night":components(nightSky),@"fog":components(fogSky)}];
    for(NSString *fragment in @[@"framebufferFragment",@"overlayFragment"]){
        Pixel input{80,120,200,64};Pixel baseline=[probe render:fragment conditions:day distance:0 color:input cutoff:0 sourceAlpha:NO];
        for(auto conditions:{night,fog})requireTest(same(baseline,[probe render:fragment conditions:conditions distance:0 color:input cutoff:0 sourceAlpha:NO]),"Conditions tinted original framebuffer or HUD");
        [checks addObject:@{@"check":fragment,@"day_night_fog_identical":@YES,@"pixel":components(baseline)}];
    }
    probe.blendMode=static_cast<NSInteger>(BlendMode::Modulate2x);
    Pixel neutral=world(night,40000,Pixel{128,128,128,255});
    requireTest(separation(neutral,clear)<2,"Original grey glow failed to preserve destination at neutral intensity");
    requireTest(separation(world(night,40000,Pixel{255,255,255,255}),Pixel{26,34,46,255})<2,"Original glow did not multiply destination by twice the source, or fog was incorrectly applied");
    requireTest(same(world(day,100,Pixel{0,0,0,255}),Pixel{0,0,0,255}),"Modulated glow black texel is incorrect");
    probe.blendMode=static_cast<NSInteger>(BlendMode::SourceColor);
    requireTest(separation(world(day,100,Pixel{64,64,64,255}),Pixel{67,68,70,255})<2,"Original ONE/SRC_COLOR material blend is incorrect");
    probe.blendMode=static_cast<NSInteger>(BlendMode::Alpha);
    requireTest(separation(world(day,100,Pixel{200,80,40,128}),Pixel{107,49,32,255})<2,"S1 glow/shadow source-alpha blending is incorrect");
    [checks addObject:@{@"check":@"original_glow_blend_equations",@"modulate2x_neutral":components(neutral),@"passed":@YES}];
    NSDictionary *report=@{@"passed":@YES,@"device":probe.device.name,@"checks":checks,@"cpu_transitions":@"default, parsing, smooth midpoint, interruption continuity, completion and finite uniform guards passed",@"scope":@"Production GPU shaders with authored synthetic geometry/colors; no game engine, input, original assets or saves"};
    NSData *data=[NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:nil];
    requireTest([data writeToFile:[NSString stringWithUTF8String:argv[2]] atomically:YES],"Cannot write conditions report");
    puts("Conditions CPU transitions and production GPU world/sky/fog/alpha/HUD probes passed. No game execution.");return 0;
}catch(const std::exception &error){fprintf(stderr,"Conditions regression: %s\n",error.what());return 1;}}}
