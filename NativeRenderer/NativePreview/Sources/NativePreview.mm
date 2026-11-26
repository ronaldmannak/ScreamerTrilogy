#import <AppKit/AppKit.h>
#import <MetalKit/MetalKit.h>
#import <QuartzCore/QuartzCore.h>
#import <QuartzCore/CAMetalDisplayLink.h>
#include <simd/simd.h>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <fstream>
#include <deque>
#include <memory>
#include <map>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>
#include <set>
#include <atomic>
#include <unistd.h>

using simd::float2; using simd::float3; using simd::float4; using simd::float4x4;
struct Vertex { float x,y,z,u,v,r,g,b,a; };
static_assert(sizeof(Vertex)==36, "Scene vertex layout must remain 36 bytes");
struct Uniforms { float4x4 matrix; float4 eye; float4 options; float4x4 model; float4x4 reflectionWorldToView; float4 reflectionScroll; };
struct Pose { uint32_t model; float3 position; simd::quatf rotation;float2 reflectionScroll={0,0};uint32_t reflectionPhase=0; };
struct CarInstance { std::string id; Pose captured; };
struct Batch { uint32_t first,count; NSInteger texture; float alphaTest; bool blend=false; NSInteger instance=-1; float3 center={0,0,0};bool s1Reflection=false;std::vector<NSInteger> reflectionTextures={};bool doubleSided=false; };
struct CameraSample { double t; float3 eye; simd::float3x3 rotation; std::map<std::string,Pose> cars; };
struct Projection { float width=640,height=480,fx=256,fy=307.2f,cx=319,cy=312,nearZ=128; };
struct HudRect {float x,y,width,height;std::string anchor;};
struct HudLayer { HudRect rect;NSString *path=nil,*format=nil;NSUInteger stride=0; };
struct LiveFrame {
    uint64_t seq=0; double sampleAt=0,publishedAt=0,period=.03;
    std::string epoch,mode,status,worldScene,carsScene,assetsEpoch,rendererNotice;
    CameraSample pose{};Projection projection;bool hasCamera=false;float originalDrawDistance=0;
    NSString *framePath=nil,*frameFormat=nil;NSUInteger frameWidth=0,frameHeight=0,frameStride=0;
    uint64_t frameSequence=0;
    bool hudComplete=false,hudPrimaryValidated=false;std::vector<HudRect> hud;
    std::vector<HudLayer> hudLayers;uint64_t hudSequence=0;
    NSString *skyPath=nil;std::string skyKind="rally";float skyCenterY=260,skyViewLastY=400;bool skyEnabled=false;float3 skyGround={0,0,0},skyFlat={0,0,0};
    bool hasSky=false,cullBackFaces=false,diagnosticCapture=false;std::set<std::string> hiddenInstanceIds;
};
struct FramebufferUniforms { float4 destination;float4 source; };

static CGSize synchronizeGameDrawable(MTKView *view) {
    // CAMetalDisplayLink bypasses MTKView's lazy currentDrawable updates.
    // Keep the actual layer in sync, including after fullscreen/backing changes.
    CGSize size=[view convertRectToBacking:view.bounds].size;
    if(!std::isfinite(size.width)||!std::isfinite(size.height)||size.width<=0||size.height<=0)return CGSizeZero;
    size.width=std::max(1.0,round(size.width));size.height=std::max(1.0,round(size.height));
    view.autoResizeDrawable=NO;
    if(!CGSizeEqualToSize(view.drawableSize,size))view.drawableSize=size;
    if([view.layer isKindOfClass:CAMetalLayer.class]){
        CAMetalLayer *layer=(CAMetalLayer *)view.layer;
        if(!CGSizeEqualToSize(layer.drawableSize,size))layer.drawableSize=size;
    }
    return size;
}


static double nowSeconds() { return CACurrentMediaTime(); }
static bool nativeMode(const std::string &mode) { return mode=="race"||mode=="attract"; }
static NSString *applicationTitle() {
    id title=NSBundle.mainBundle.infoDictionary[@"CFBundleDisplayName"];
    return [title isKindOfClass:NSString.class]&&[title length] ? title : @"Screamer Metal";
}
static float3 vector3(NSArray *a) {
    if (![a isKindOfClass:NSArray.class] || a.count!=3) throw std::runtime_error("Expected three coordinates");
    for(id value in a)if(![value isKindOfClass:NSNumber.class])throw std::runtime_error("Coordinates must be numeric");
    float3 v={(float)[a[0] doubleValue],(float)[a[1] doubleValue],(float)[a[2] doubleValue]};
    if (!std::isfinite(v.x) || !std::isfinite(v.y) || !std::isfinite(v.z)) throw std::runtime_error("Non-finite coordinate");
    return v;
}
static Pose poseFromJSON(NSDictionary *j) {
    if(![j isKindOfClass:NSDictionary.class] || ![j[@"model"] isKindOfClass:NSNumber.class])throw std::runtime_error("Invalid car pose/model");
    double model=[j[@"model"] doubleValue];
    if(!std::isfinite(model)||model<0||model>4095||floor(model)!=model)throw std::runtime_error("Invalid car model index");
    NSArray *values=j[@"rotation"];
    if(![values isKindOfClass:NSArray.class]||values.count!=9)throw std::runtime_error("Car rotation requires nine numbers");
    simd::float3x3 rotation;
    for(int col=0;col<3;col++)for(int row=0;row<3;row++){
        id value=values[row*3+col];if(![value isKindOfClass:NSNumber.class]||!std::isfinite([value floatValue]))throw std::runtime_error("Invalid car rotation value");
        rotation.columns[col][row]=[value floatValue];
    }
    auto identity=simd_transpose(rotation)*rotation;float error=0;
    for(int col=0;col<3;col++)for(int row=0;row<3;row++)error=std::max(error,fabsf(identity.columns[col][row]-(row==col?1.f:0.f)));
    if(error>.01f||fabsf(simd_determinant(rotation)-1)>.01f)throw std::runtime_error("Car rotation must be proper and orthogonal");
    float2 scroll={0,0};id scrollValues=j[@"reflection_scroll"];
    if(scrollValues){
        if(![scrollValues isKindOfClass:NSArray.class]||[scrollValues count]!=2)throw std::runtime_error("Invalid reflection scroll");
        for(int n=0;n<2;n++){id v=scrollValues[n];if(![v isKindOfClass:NSNumber.class]||!std::isfinite([v floatValue])||[v floatValue]<0||[v floatValue]>=1)throw std::runtime_error("Reflection scroll exceeds source range");scroll[n]=[v floatValue];}
    }
    uint32_t phase=0;id phaseValue=j[@"reflection_phase"];
    if(phaseValue){double value=[phaseValue isKindOfClass:NSNumber.class]?[phaseValue doubleValue]:-1;
        if(!std::isfinite(value)||value<0||value>65535||floor(value)!=value)throw std::runtime_error("Invalid original reflection phase");phase=(uint32_t)value;}
    return {(uint32_t)model,vector3(j[@"position"]),simd_normalize(simd_quaternion(rotation)),scroll,phase};
}
static float4x4 poseMatrix(const Pose &a,const Pose &b,float alpha) {
    auto rotation=simd_slerp(a.rotation,b.rotation,std::clamp(alpha,0.f,1.f));
    float4x4 matrix=simd_matrix4x4(rotation);float3 p=simd_mix(a.position,b.position,alpha);
    matrix.columns[3]=(float4){p.x,p.y,p.z,1};return matrix;
}
static NSDictionary *jsonFile(NSString *path) {
    NSDictionary *attributes=[NSFileManager.defaultManager attributesOfItemAtPath:path error:nil];
    if(!attributes||[attributes fileSize]>64*1024*1024)throw std::runtime_error("Missing or oversized JSON input");
    NSError *e=nil; NSData *d=[NSData dataWithContentsOfFile:path options:0 error:&e];
    id j=d ? [NSJSONSerialization JSONObjectWithData:d options:0 error:&e] : nil;
    if (![j isKindOfClass:NSDictionary.class]) throw std::runtime_error([[NSString stringWithFormat:@"Cannot read JSON %@: %@",path,e.localizedDescription] UTF8String]);
    return j;
}
static NSString *assetPath(NSString *base, NSString *relative) {
    if (![relative isKindOfClass:NSString.class] || relative.isAbsolutePath || [relative.pathComponents containsObject:@".."])
        throw std::runtime_error("Scene assets must use safe relative paths");
    return [base stringByAppendingPathComponent:relative];
}
static std::vector<float> sceneNormals(NSDictionary *scene,NSString *base,size_t count) {
    std::vector<float> normals(count*3,0);id header=scene[@"normals"];
    if(!header)return normals;
    if(![header isKindOfClass:NSDictionary.class]||![header[@"format"] isEqual:@"float32-le"]||![header[@"space"] isEqual:@"vertex-local"]||[header[@"stride"] unsignedIntegerValue]!=12||[header[@"count"] unsignedLongLongValue]!=count)throw std::runtime_error("Invalid authored normal buffer header");
    NSData *raw=[NSData dataWithContentsOfFile:assetPath(base,header[@"file"])];
    if(raw.length!=normals.size()*sizeof(float))throw std::runtime_error("Invalid authored normal buffer length");
    memcpy(normals.data(),raw.bytes,raw.length);
    for(float value:normals)if(!std::isfinite(value)||fabsf(value)>8)throw std::runtime_error("Invalid authored normal component");
    return normals;
}
static bool s1ReflectionBatch(NSDictionary *batch,NSDictionary *scene) {
    if(![batch[@"texgen"] isEqual:@"s1-reflection"])return false;
    if([batch[@"source_material_type"] unsignedIntegerValue]!=0xa0||!scene[@"normals"]||[batch[@"blend"] boolValue]||[batch[@"alpha_test"] boolValue]||![batch[@"texture"] isKindOfClass:NSNumber.class]||[batch[@"texture"] integerValue]<0)throw std::runtime_error("S1 glass requires authored normals and opaque original texture");
    return true;
}
static std::vector<NSInteger> reflectionTextures(NSDictionary *batch,NSUInteger count,NSInteger offset) {
    id frames=batch[@"reflection_textures"];if(!frames)return {};
    if(![frames isKindOfClass:NSArray.class]||[frames count]<1||[frames count]>256)throw std::runtime_error("Invalid reflection texture frame list");
    std::vector<NSInteger> result;
    for(id frame in frames){double value=[frame isKindOfClass:NSNumber.class]?[frame doubleValue]:-1;
        if(!std::isfinite(value)||value<0||value>=count||floor(value)!=value)throw std::runtime_error("Reflection texture frame exceeds scene table");result.push_back(offset+(NSInteger)value);}
    return result;
}
static NSInteger reflectionTexture(const Batch &batch,uint32_t phase) {
    if(!batch.s1Reflection||batch.reflectionTextures.empty())return batch.texture;
    return batch.reflectionTextures[((size_t)phase*batch.reflectionTextures.size())>>16];
}
static float2 interpolatedReflectionScroll(const Pose &a,const Pose &b,float alpha) {
    float2 delta=b.reflectionScroll-a.reflectionScroll;
    for(int n=0;n<2;n++)delta[n]-=roundf(delta[n]);
    return a.reflectionScroll+alpha*delta;
}
static float4x4 perspective(float fovy,float aspect,float nearZ,float farZ) {
    float sy=1.0f/tanf(fovy*0.5f),sx=sy/aspect,z=farZ/(nearZ-farZ);
    return (float4x4){(float4){sx,0,0,0},(float4){0,sy,0,0},(float4){0,0,z,-1},(float4){0,0,z*nearZ,0}};
}
static float4x4 replayProjection(const Projection &p,float aspect,float farZ) {
    // Preserve vertical framing and extend horizontal field of view for wide windows.
    float sx=2*p.fx/p.height/aspect,sy=2*p.fy/p.height;
    float ox=(2*p.cx/p.width-1)*(p.width/p.height)/aspect,oy=1-2*p.cy/p.height;
    float z=farZ/(p.nearZ-farZ);
    return (float4x4){(float4){sx,0,0,0},(float4){0,sy,0,0},(float4){-ox,-oy,z,-1},(float4){0,0,z*p.nearZ,0}};
}
static void checkProjectionMath() {
    Projection p;
    auto close=[](float a,float b){if(!std::isfinite(a)||fabsf(a-b)>.0001f)throw std::runtime_error("Projection reference check failed");};
    float4x4 matrix=replayProjection(p,4.f/3.f,100000);
    // Identity game camera looks toward negative world Z; X is reflected.
    float4 center=matrix*(float4){0,0,-1000,1};
    close((center.x/center.w+1)*320,319);close((1-center.y/center.w)*240,312);
    float4 right=matrix*(float4){1000,0,-1000,1};
    close((right.x/right.w+1)*320,575);
    float4 up=matrix*(float4){0,500,-1000,1};
    close((1-up.y/up.w)*240,158.4f);
    float4 nearPoint=matrix*(float4){0,0,-128,1},farPoint=matrix*(float4){0,0,-100000,1};
    close(nearPoint.z/nearPoint.w,0);close(farPoint.z/farPoint.w,1);
    auto wide=replayProjection(p,16.f/9.f,100000);
    close(wide.columns[1].y,matrix.columns[1].y);
    close(wide.columns[0].x/matrix.columns[0].x,.75f);
    Pose a{1,{0,0,0},simd_quaternion(0.f,(float3){0,1,0})};
    Pose b{1,{10,20,30},simd_quaternion((float)M_PI_2,(float3){0,1,0})};
    auto midpoint=poseMatrix(a,b,.5f);close(midpoint.columns[3].x,5);close(midpoint.columns[3].y,10);close(midpoint.columns[3].z,15);
    auto direction=midpoint*(float4){1,0,0,0};close(direction.x,sqrtf(.5f));close(direction.z,-sqrtf(.5f));
}
static float4x4 orbitRotation(float3 eye,float3 target) {
    float3 z=simd_normalize(eye-target),x=simd_normalize(simd_cross((float3){0,1,0},z)),y=simd_cross(z,x);
    return (float4x4){(float4){x.x,y.x,z.x,0},(float4){x.y,y.y,z.y,0},(float4){x.z,y.z,z.z,0},(float4){0,0,0,1}};
}
static double percentile(std::vector<double> v,double fraction) {
    if (v.empty()) return 0; std::sort(v.begin(),v.end());
    return v[(size_t)std::floor((v.size()-1)*fraction)];
}
static LiveFrame liveFrameFromJSON(NSDictionary *j,NSString *base) {
    if(![j[@"schema"] isEqual:@"screamer-live/v1"]||![j[@"epoch"] isKindOfClass:NSString.class]||![j[@"seq"] isKindOfClass:NSNumber.class])throw std::runtime_error("Invalid live state contract");
    LiveFrame frame;frame.epoch=[j[@"epoch"] UTF8String];frame.seq=[j[@"seq"] unsignedLongLongValue];
    if(frame.epoch.empty()||frame.epoch.size()>128)throw std::runtime_error("Invalid live epoch");
    frame.mode=[j[@"mode"] isKindOfClass:NSString.class]?[j[@"mode"] UTF8String]:"framebuffer";
    frame.status=[j[@"status"] isKindOfClass:NSString.class]?[j[@"status"] UTF8String]:"loading";
    if([j[@"renderer_notice"] isKindOfClass:NSString.class]&&[j[@"renderer_notice"] length]<=512)frame.rendererNotice=[j[@"renderer_notice"] UTF8String];
    frame.sampleAt=j[@"sample_monotonic_ns"]?[j[@"sample_monotonic_ns"] doubleValue]*1e-9:[j[@"timestamp_monotonic"] doubleValue];
    frame.publishedAt=j[@"published_monotonic_ns"]?[j[@"published_monotonic_ns"] doubleValue]*1e-9:frame.sampleAt;
    frame.period=j[@"physics_period_ms"]?[j[@"physics_period_ms"] doubleValue]*.001:.03;
    if(!std::isfinite(frame.sampleAt)||frame.sampleAt<=0||!std::isfinite(frame.publishedAt)||!std::isfinite(frame.period)||frame.period<.01||frame.period>.2)throw std::runtime_error("Invalid live clock");
    auto resolved=[&](id value)->NSString *{if(![value isKindOfClass:NSString.class])return nil;return [value isAbsolutePath]?value:assetPath(base,value);};
    NSDictionary *assets=j[@"assets"];
    if([assets isKindOfClass:NSDictionary.class]){
        NSString *world=resolved(assets[@"world_scene"]),*cars=resolved(assets[@"cars_scene"]);
        if([assets[@"epoch"] isKindOfClass:NSString.class])frame.assetsEpoch=[assets[@"epoch"] UTF8String];
        if(world)frame.worldScene=world.UTF8String;if(cars)frame.carsScene=cars.UTF8String;
        frame.skyPath=resolved(assets[@"sky_texture"]);
    }
    NSDictionary *sky=j[@"sky"];
    if([sky isKindOfClass:NSDictionary.class]){
        frame.hasSky=true;frame.skyEnabled=[sky[@"enabled"] boolValue];
        if([sky[@"kind"] isEqual:@"s1"]){
            frame.skyKind="s1";frame.skyCenterY=[sky[@"center_y"] floatValue];frame.skyViewLastY=[sky[@"view_last_y"] floatValue];
            if(!std::isfinite(frame.skyCenterY)||!std::isfinite(frame.skyViewLastY)||frame.skyCenterY<=0||frame.skyCenterY>=400||frame.skyViewLastY<=0||frame.skyViewLastY>400)throw std::runtime_error("Invalid original S1 sky viewport");
        }
        frame.skyGround=vector3(sky[@"ground_rgb"])/255.f;frame.skyFlat=vector3(sky[@"flat_rgb"])/255.f;
    }
    frame.cullBackFaces=[j[@"cull_back_faces"] boolValue];frame.diagnosticCapture=[j[@"diagnostic_capture_replay"] boolValue];
    NSArray *hidden=j[@"hidden_instance_ids"]?:@[];
    if(![hidden isKindOfClass:NSArray.class]||hidden.count>32)throw std::runtime_error("Invalid hidden instance table");
    for(id value in hidden){if(![value isKindOfClass:NSString.class]||[value length]>128)throw std::runtime_error("Invalid hidden instance ID");frame.hiddenInstanceIds.insert([value UTF8String]);}
    NSDictionary *fb=j[@"framebuffer"];
    if([fb isKindOfClass:NSDictionary.class]){
        frame.framePath=resolved(fb[@"path"]);frame.frameFormat=fb[@"format"]?:@"png";
        frame.frameWidth=[fb[@"width"] unsignedIntegerValue];frame.frameHeight=[fb[@"height"] unsignedIntegerValue];frame.frameStride=[fb[@"stride"] unsignedIntegerValue];
        frame.frameSequence=fb[@"sequence"]?[fb[@"sequence"] unsignedLongLongValue]:frame.seq;
    }
    NSDictionary *hud=j[@"hud"];
    if([hud isKindOfClass:NSDictionary.class]&&([hud[@"complete"] boolValue]||[hud[@"primary_hud_validated"] boolValue])){
        NSArray *rects=hud[@"rects"]?:@[];
        if(![rects isKindOfClass:NSArray.class]||rects.count>64)throw std::runtime_error("Invalid HUD rectangle table");
        for(NSDictionary *rect in rects){
            if(![rect isKindOfClass:NSDictionary.class])throw std::runtime_error("Invalid HUD rectangle");
            HudRect h{[rect[@"x"] floatValue],[rect[@"y"] floatValue],[rect[@"width"] floatValue],[rect[@"height"] floatValue],"center"};
            if(!std::isfinite(h.x)||!std::isfinite(h.y)||!std::isfinite(h.width)||!std::isfinite(h.height)||h.x<0||h.y<0||h.width<=0||h.height<=0||h.x+h.width>frame.frameWidth||h.y+h.height>frame.frameHeight)throw std::runtime_error("HUD rectangle outside original framebuffer");
            if([rect[@"anchor"] isKindOfClass:NSString.class])h.anchor=[rect[@"anchor"] UTF8String];
            if(h.anchor!="left"&&h.anchor!="right"&&h.anchor!="center"&&h.anchor!="stretch")throw std::runtime_error("Invalid HUD anchor");frame.hud.push_back(h);
        }
        NSArray *layers=hud[@"layers"]?:@[];
        if(![layers isKindOfClass:NSArray.class]||layers.count>16)throw std::runtime_error("Invalid HUD layer table");
        for(NSDictionary *layer in layers){
            if(![layer isKindOfClass:NSDictionary.class])throw std::runtime_error("Invalid HUD layer");
            HudLayer value;value.rect={[layer[@"x"] floatValue],[layer[@"y"] floatValue],[layer[@"width"] floatValue],[layer[@"height"] floatValue],"center"};
            auto &r=value.rect;
            if(!std::isfinite(r.x)||!std::isfinite(r.y)||!std::isfinite(r.width)||!std::isfinite(r.height)||r.x<0||r.y<0||r.width<=0||r.height<=0||r.x+r.width>frame.frameWidth||r.y+r.height>frame.frameHeight||floorf(r.width)!=r.width||floorf(r.height)!=r.height)throw std::runtime_error("HUD layer outside source frame");
            if([layer[@"anchor"] isKindOfClass:NSString.class])r.anchor=[layer[@"anchor"] UTF8String];
            if(r.anchor!="left"&&r.anchor!="right"&&r.anchor!="center"&&r.anchor!="stretch")throw std::runtime_error("Invalid HUD layer anchor");
            value.path=resolved(layer[@"path"]);value.format=layer[@"format"]?:@"bgra8";value.stride=[layer[@"stride"] unsignedIntegerValue];
            if(!value.path||![value.format isEqual:@"bgra8"]||value.stride<(NSUInteger)r.width*4||value.stride>65536)throw std::runtime_error("Invalid HUD layer pixels");
            frame.hudLayers.push_back(value);
        }
        frame.hudSequence=hud[@"sequence"]?[hud[@"sequence"] unsignedLongLongValue]:frame.frameSequence;
        bool anyOverlay=!frame.hud.empty()||!frame.hudLayers.empty();
        frame.hudComplete=[hud[@"complete"] boolValue]&&anyOverlay;
        frame.hudPrimaryValidated=[hud[@"primary_hud_validated"] boolValue]&&anyOverlay;
    }
    NSDictionary *camera=j[@"camera"];
    if(nativeMode(frame.mode)&&[camera isKindOfClass:NSDictionary.class]){
        NSArray *matrix=camera[@"rotation"];
        if(![matrix isKindOfClass:NSArray.class]||matrix.count!=9)throw std::runtime_error("Invalid live camera rotation");
        simd::float3x3 proper;
        for(int col=0;col<3;col++)for(int row=0;row<3;row++){
            id v=matrix[row*3+col];if(![v isKindOfClass:NSNumber.class]||!std::isfinite([v floatValue]))throw std::runtime_error("Invalid live camera component");
            proper.columns[col][row]=-[v floatValue];
        }
        auto identity=simd_transpose(proper)*proper;float error=0;
        for(int col=0;col<3;col++)for(int row=0;row<3;row++)error=std::max(error,fabsf(identity.columns[col][row]-(row==col?1.f:0.f)));
        if(error>.01f||fabsf(simd_determinant(proper)-1)>.01f)throw std::runtime_error("Invalid live camera handedness");
        frame.pose={frame.sampleAt,vector3(camera[@"position"]),proper,{}};
        NSDictionary *projection=camera[@"projection"];
        if(![projection isKindOfClass:NSDictionary.class])throw std::runtime_error("Missing live projection");
        NSArray *keys=@[@"width",@"height",@"fx",@"fy",@"cx",@"cy",@"near"];float p[7];
        for(int n=0;n<7;n++){id v=projection[keys[n]];if(![v isKindOfClass:NSNumber.class]||!std::isfinite([v floatValue]))throw std::runtime_error("Invalid live projection component");p[n]=[v floatValue];}
        if(p[0]<=0||p[1]<=0||p[2]<=0||p[3]<=0||p[6]<=0)throw std::runtime_error("Invalid live projection scale");
        frame.projection={p[0],p[1],p[2],p[3],p[4],p[5],p[6]};frame.hasCamera=true;
        id distance=camera[@"original_draw_distance"];
        if([distance isKindOfClass:NSNumber.class]&&std::isfinite([distance floatValue])&&[distance floatValue]>p[6]&&[distance floatValue]<=10000000)frame.originalDrawDistance=[distance floatValue];
        NSArray *instances=j[@"instances"];
        if(![instances isKindOfClass:NSArray.class]||instances.count>1024)throw std::runtime_error("Invalid live instance table");
        for(NSDictionary *pose in instances){
            if(![pose isKindOfClass:NSDictionary.class]||![pose[@"id"] isKindOfClass:NSString.class])throw std::runtime_error("Invalid live instance");
            std::string id=[pose[@"id"] UTF8String];if(frame.pose.cars.count(id))throw std::runtime_error("Duplicate live instance");frame.pose.cars.emplace(id,poseFromJSON(pose));
        }
    }
    return frame;
}
struct State {
    id<MTLDevice> device;
    id<MTLCommandQueue> queue;
    id<MTLRenderPipelineState> pipeline;
    id<MTLRenderPipelineState> blendPipeline;
    id<MTLRenderPipelineState> framebufferPipeline;
    id<MTLRenderPipelineState> presentationPipeline;
    id<MTLRenderPipelineState> overlayPipeline,skyPipeline;
    id<MTLDepthStencilState> depthState;
    id<MTLDepthStencilState> blendDepthState;
    id<MTLSamplerState> sampler;
    id<MTLSamplerState> skySampler;
    id<MTLBuffer> vertexBuffer,indexBuffer,normalBuffer;
    NSMutableArray<id<MTLTexture>> *textures;
    id<MTLTexture> whiteTexture,depthTexture;
    id<MTLTexture> render4KTexture;
    id<MTLTexture> widescreenTexture,skyTexture;
    NSString *loadedSkyPath=nil,*hudEpoch=nil;uint64_t loadedHudSequence=UINT64_MAX;
    NSMutableArray<id<MTLTexture>> *hudTextures;
    bool hudLayersReady=false,skyActive=false;
    bool cullBackFaces=false,diagnosticCapture=false;
    bool render4K=false,widescreen=true,extendedDistance=true;float activeFarPlane=0;
    std::vector<Batch> batches;
    std::vector<CameraSample> replay;
    std::vector<CarInstance> cars;
    uint64_t carTriangles=0,carPoseSamples=0,visibleCars=0,reflectionTriangles=0,reflectionDraws=0;bool independentParts=false;
    NSString *carsPath;
    Projection projection;
    NSString *shaderPath,*livePath,*inputPath,*liveEpoch;
    NSTask *sessionTask=nil;NSFileHandle *sessionLog=nil;NSString *sessionDirectory=nil,*startupError=nil;
    dispatch_source_t livePoller=nil,inputHeartbeat=nil;
    std::mutex liveLock;
    std::deque<LiveFrame> liveFrames;
    uint64_t liveParseErrors=0,liveStates=0,inputSeq=0,framebufferSeq=UINT64_MAX;
    NSMutableSet<NSString *> *pressedKeys;
    NSMutableDictionary<NSNumber *,NSString *> *pressedCodes;
    NSMutableDictionary<NSString *,NSNumber *> *pressCounts;
    bool sessionStopping=false,inputFocused=false,liveNative=false,liveAssetsReady=false,liveAssetLoading=false,liveSceneOnly=false;
    bool allowPartialHud=false,livePartialHud=false,originalView=false,bundledGameUI=false;
    NSString *liveNotice=nil;
    double liveAge=0,livePoseAge=0,liveDelay=.03,liveClockOffset=0;bool liveClockInitialized=false;
    id<MTLTexture> framebufferTexture=nil;
    NSString *framebufferEpoch=nil;
    NSString *loadedWorldScene,*loadedCarsScene,*loadedAssetsEpoch;
    double lastAssetAttempt=0;
    float3 center={0,0,0}; float radius=1,distance=1,yaw=0.5f,pitch=0.85f;
    bool animate=true,followReplay=true;
    double started=nowSeconds(),lastTitle=0;
    uint64_t frames=0,nativeFrames=0,fallbackFrames=0,triangles=0,vertices=0;
    NSUInteger renderWidth=0,renderHeight=0;
    NSUInteger drawableWidth=0,drawableHeight=0;double windowContentWidth=0,windowContentHeight=0;
    CGSize viewBoundsSize={},viewFrameSize={},viewBackingSize={},viewDrawableSize={},layerBoundsSize={},layerDrawableSize={},windowLayoutSize={};
    uint64_t staleDrawableDrops=0;bool fullScreen=false;
    NSString *scenePath,*reportPath,*sceneName;
    std::mutex metricsLock;
    std::vector<double> gpuMs,encodeMs,presentedTimes,drawableWaitMs,drawTimes;
    uint64_t gpuErrors=0;
    NSString *lastGpuError=nil;
    NSString *displayScheduler=@"MTKView-60";
    std::atomic<bool> foreground{false};std::atomic<uint64_t> foregroundGeneration{0};
    uint64_t foregroundPresented=0,lastForegroundGeneration=UINT64_MAX;double lastForegroundPresent=0;
    std::vector<double> foregroundIntervals,displayTargetTimes;
    double duration=0,fixedTime=-1;
    dispatch_semaphore_t inFlight=dispatch_semaphore_create(3);
};

@interface PreviewRenderer : NSObject<MTKViewDelegate> { @public std::unique_ptr<State> state; }
- (instancetype)initWithScene:(NSString *)scene shader:(NSString *)shader replay:(NSString *)replay cars:(NSString *)cars report:(NSString *)report;
- (id<MTLCommandBuffer>)encodeTo:(id<MTLTexture>)target drawable:(id<CAMetalDrawable>)drawable;
- (NSDictionary *)metrics;
- (void)writeReport;
- (void)startLive:(NSString *)path input:(NSString *)input;
- (void)publishInput;
- (void)releaseInput;
- (void)setGameKey:(NSString *)key code:(unsigned short)code down:(BOOL)down;
- (void)pollLive;
- (void)updateFramebuffer:(const LiveFrame &)frame;
- (void)updateOverlays:(const LiveFrame &)frame;
- (void)requestLiveAssets:(const LiveFrame &)frame;
- (void)stopSession;
- (void)renderDrawable:(id<CAMetalDrawable>)drawable inView:(MTKView *)view callbackAt:(double)begin drawableWait:(double)wait;
- (void)setForeground:(BOOL)active;
@end
@implementation PreviewRenderer
- (instancetype)initWithScene:(NSString *)scene shader:(NSString *)shader replay:(NSString *)replay cars:(NSString *)cars report:(NSString *)report {
    self=[super init]; if (!self) return nil;
    state=std::make_unique<State>(); State &s=*state;
    s.shaderPath=shader;s.loadedWorldScene=scene;s.loadedCarsScene=cars;
    s.pressedKeys=[NSMutableSet set];s.pressedCodes=[NSMutableDictionary dictionary];s.pressCounts=[NSMutableDictionary dictionary];
    s.scenePath=scene;s.reportPath=report;s.sceneName=@"Screamer Rally";
    s.device=MTLCreateSystemDefaultDevice();
    if (!s.device) throw std::runtime_error("No Metal device available");
    s.queue=[s.device newCommandQueue];
    NSDictionary *j=jsonFile(scene);NSString *base=scene.stringByDeletingLastPathComponent;
    s.sceneName=j[@"title"] ?: @"Screamer Rally track";
    id vertexInfo=j[@"vertices"],indexInfo=j[@"indices"];
    NSString *vertexName=[vertexInfo isKindOfClass:NSDictionary.class] ? vertexInfo[@"file"] : (vertexInfo ?: @"vertices.bin");
    NSString *indexName=[indexInfo isKindOfClass:NSDictionary.class] ? indexInfo[@"file"] : (indexInfo ?: @"indices.bin");
    NSData *v=[NSData dataWithContentsOfFile:assetPath(base,vertexName)],*i=[NSData dataWithContentsOfFile:assetPath(base,indexName)];
    if (!v.length || v.length%sizeof(Vertex) || !i.length || i.length%sizeof(uint32_t)) throw std::runtime_error("Invalid mesh buffer lengths");
    s.vertices=v.length/sizeof(Vertex);s.triangles=i.length/sizeof(uint32_t)/3;
    const uint32_t *indices=(const uint32_t *)i.bytes;
    for (NSUInteger n=0;n<i.length/4;n++) if (indices[n]>=s.vertices) throw std::runtime_error("Mesh index out of bounds");
    const Vertex *vv=(const Vertex *)v.bytes;
    for (NSUInteger n=0;n<s.vertices;n++) if (!std::isfinite(vv[n].x)||!std::isfinite(vv[n].y)||!std::isfinite(vv[n].z)) throw std::runtime_error("Non-finite mesh vertex");
    std::vector<float> normals=sceneNormals(j,base,s.vertices);
    s.normalBuffer=[s.device newBufferWithBytes:normals.data() length:normals.size()*sizeof(float) options:MTLResourceStorageModeShared];
    s.vertexBuffer=[s.device newBufferWithBytes:v.bytes length:v.length options:MTLResourceStorageModeShared];
    s.indexBuffer=[s.device newBufferWithBytes:i.bytes length:i.length options:MTLResourceStorageModeShared];
    float3 lo=vector3(j[@"bounds"][@"min"]),hi=vector3(j[@"bounds"][@"max"]);
    s.center=(lo+hi)*0.5f;s.radius=std::max(simd_length(hi-lo)*0.5f,1.f);s.distance=s.radius*1.65f;
    for (NSDictionary *b in j[@"batches"]) {
        uint64_t first=[b[@"first_index"] unsignedLongLongValue],count=[b[@"index_count"] unsignedLongLongValue];
        if (!count || count%3 || first>i.length/4 || count>i.length/4-first || first>UINT32_MAX || count>UINT32_MAX) throw std::runtime_error("Invalid draw batch");
        if ([b[@"blend"] boolValue])throw std::runtime_error("Blended materials require a later renderer stage");
        NSInteger texture=[b[@"texture"] isKindOfClass:NSNumber.class] ? [b[@"texture"] integerValue] : -1;
        s.batches.push_back({(uint32_t)first,(uint32_t)count,texture,[b[@"alpha_test"] boolValue] ? 0.5f : 0.f});
        s.batches.back().s1Reflection=s1ReflectionBatch(b,j);s.batches.back().doubleSided=[b[@"double_sided"] boolValue];
        if(s.batches.back().s1Reflection)s.batches.back().reflectionTextures=reflectionTextures(b,[j[@"textures"] count],0);
    }
    if (s.batches.empty()) s.batches.push_back({0,(uint32_t)(i.length/4),-1,0});
    s.textures=[NSMutableArray array];MTKTextureLoader *loader=[[MTKTextureLoader alloc] initWithDevice:s.device];
    for (id texture in j[@"textures"]) {
        NSString *name=[texture isKindOfClass:NSString.class] ? texture : texture[@"path"];
        NSError *error=nil;id<MTLTexture> t=[loader newTextureWithContentsOfURL:[NSURL fileURLWithPath:assetPath(base,name)] options:@{MTKTextureLoaderOptionSRGB:@NO,MTKTextureLoaderOptionGenerateMipmaps:@YES} error:&error];
        if (!t) throw std::runtime_error([[NSString stringWithFormat:@"Cannot load texture %@: %@",name,error.localizedDescription] UTF8String]);
        [s.textures addObject:t];
    }
    for(const Batch &b:s.batches)if(b.texture>=0 && b.texture>=(NSInteger)s.textures.count)throw std::runtime_error("Texture index out of bounds");
    if(cars){
        s.carsPath=cars;NSDictionary *cj=jsonFile(cars);s.independentParts=[cj[@"statistics"][@"dynamic_part_instances"] unsignedIntegerValue]>0;NSString *carBase=cars.stringByDeletingLastPathComponent;
        NSArray *instances=cj[@"dynamic_instances"];
        if(![instances isKindOfClass:NSArray.class]||instances.count<1||instances.count>256)throw std::runtime_error("Invalid car instance table");
        std::map<std::string,NSInteger> instanceIndices;
        for(NSDictionary *instance in instances){
            if(![instance isKindOfClass:NSDictionary.class]||![instance[@"id"] isKindOfClass:NSString.class])throw std::runtime_error("Invalid car instance ID");
            std::string id=[instance[@"id"] UTF8String];
            if(id.empty()||id.size()>128||instanceIndices.count(id))throw std::runtime_error("Duplicate/invalid car instance ID");
            instanceIndices[id]=(NSInteger)s.cars.size();s.cars.push_back({id,poseFromJSON(instance)});
        }
        NSData *cv=[NSData dataWithContentsOfFile:assetPath(carBase,cj[@"vertices"][@"file"])],*ci=[NSData dataWithContentsOfFile:assetPath(carBase,cj[@"indices"][@"file"])];
        if(!cv.length||cv.length%sizeof(Vertex)||!ci.length||ci.length%4||ci.length/4%3)throw std::runtime_error("Invalid car mesh buffer lengths");
        uint64_t vertexBase=s.vertices,indexBase=i.length/4;
        if(vertexBase+cv.length/sizeof(Vertex)>UINT32_MAX)throw std::runtime_error("Combined mesh too large");
        const Vertex *carVertices=(const Vertex *)cv.bytes;
        for(NSUInteger n=0;n<cv.length/sizeof(Vertex);n++)if(!std::isfinite(carVertices[n].x)||!std::isfinite(carVertices[n].y)||!std::isfinite(carVertices[n].z))throw std::runtime_error("Nonfinite car vertex");
        const uint32_t *carIndices=(const uint32_t *)ci.bytes;std::vector<uint32_t> adjusted;
        for(NSUInteger n=0;n<ci.length/4;n++){if(carIndices[n]>=cv.length/sizeof(Vertex))throw std::runtime_error("Car index out of bounds");adjusted.push_back((uint32_t)vertexBase+carIndices[n]);}
        NSMutableData *combinedVertices=[v mutableCopy],*combinedIndices=[i mutableCopy];
        [combinedVertices appendData:cv];[combinedIndices appendBytes:adjusted.data() length:adjusted.size()*4];
        s.vertexBuffer=[s.device newBufferWithBytes:combinedVertices.bytes length:combinedVertices.length options:MTLResourceStorageModeShared];
        s.indexBuffer=[s.device newBufferWithBytes:combinedIndices.bytes length:combinedIndices.length options:MTLResourceStorageModeShared];
        auto carNormals=sceneNormals(cj,carBase,cv.length/sizeof(Vertex));normals.insert(normals.end(),carNormals.begin(),carNormals.end());
        s.normalBuffer=[s.device newBufferWithBytes:normals.data() length:normals.size()*sizeof(float) options:MTLResourceStorageModeShared];
        s.vertices+=cv.length/sizeof(Vertex);s.carTriangles=ci.length/12;s.triangles+=s.carTriangles;
        NSInteger textureBase=(NSInteger)s.textures.count;
        for(NSDictionary *texture in cj[@"textures"]){
            NSError *error=nil;id<MTLTexture> t=nil;
            if(texture[@"rgba_file"]){
                NSUInteger width=[texture[@"width"] unsignedIntegerValue],height=[texture[@"height"] unsignedIntegerValue];
                NSData *rgba=[NSData dataWithContentsOfFile:assetPath(carBase,texture[@"rgba_file"])];
                if(!width||!height||width>4096||height>4096||rgba.length!=width*height*4)throw std::runtime_error("Invalid raw car texture");
                auto descriptor=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:width height:height mipmapped:NO];
                descriptor.storageMode=MTLStorageModeShared;t=[s.device newTextureWithDescriptor:descriptor];
                [t replaceRegion:MTLRegionMake2D(0,0,width,height) mipmapLevel:0 withBytes:rgba.bytes bytesPerRow:width*4];
            }else t=[loader newTextureWithContentsOfURL:[NSURL fileURLWithPath:assetPath(carBase,texture[@"path"])] options:@{MTKTextureLoaderOptionSRGB:@NO,MTKTextureLoaderOptionGenerateMipmaps:@YES} error:&error];
            if(!t)throw std::runtime_error("Could not load car texture");[s.textures addObject:t];
        }
        for(NSDictionary *batch in cj[@"batches"]){
            uint64_t first=[batch[@"first_index"] unsignedLongLongValue],count=[batch[@"index_count"] unsignedLongLongValue];
            if(!count||count%3||first>ci.length/4||count>ci.length/4-first||indexBase+first>UINT32_MAX||count>UINT32_MAX)throw std::runtime_error("Invalid car draw batch");
            NSString *name=batch[@"instance_id"];
            if(![name isKindOfClass:NSString.class]||!instanceIndices.count(name.UTF8String))throw std::runtime_error("Car batch references unknown instance");
            NSInteger texture=[batch[@"texture"] isKindOfClass:NSNumber.class]?[batch[@"texture"] integerValue]:-1;
            if(texture< -1||texture>=(NSInteger)[cj[@"textures"] count])throw std::runtime_error("Car texture index out of bounds");
            bool blend=[batch[@"blend"] boolValue];if(blend&&[batch[@"mode"] intValue]!=6)throw std::runtime_error("Only source-alpha car blending is supported");
            float3 low={INFINITY,INFINITY,INFINITY},high={-INFINITY,-INFINITY,-INFINITY};
            for(uint64_t n=first;n<first+count;n++){const Vertex &vv=carVertices[carIndices[n]];float3 point={vv.x,vv.y,vv.z};low=simd_min(low,point);high=simd_max(high,point);}
            s.batches.push_back({(uint32_t)(indexBase+first),(uint32_t)count,texture<0?-1:textureBase+texture,
                [batch[@"alpha_test"] boolValue]?.5f:0.f,blend,instanceIndices[name.UTF8String],(low+high)*.5f});
            s.batches.back().s1Reflection=s1ReflectionBatch(batch,cj);s.batches.back().doubleSided=[batch[@"double_sided"] boolValue];
            if(s.batches.back().s1Reflection)s.batches.back().reflectionTextures=reflectionTextures(batch,[cj[@"textures"] count],textureBase);
        }
    }
    for(const auto &batch:s.batches)if(batch.s1Reflection)s.reflectionTriangles+=batch.count/3;
    MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:1 height:1 mipmapped:NO];
    s.whiteTexture=[s.device newTextureWithDescriptor:td];uint32_t white=0xffffffff;
    [s.whiteTexture replaceRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0 withBytes:&white bytesPerRow:4];
    NSError *error=nil;NSString *source=[NSString stringWithContentsOfFile:shader encoding:NSUTF8StringEncoding error:&error];
    id<MTLLibrary> library=source ? [s.device newLibraryWithSource:source options:nil error:&error] : nil;
    if (!library) throw std::runtime_error([[NSString stringWithFormat:@"Metal shader compilation failed: %@",error.localizedDescription] UTF8String]);
    MTLRenderPipelineDescriptor *pd=[MTLRenderPipelineDescriptor new];pd.label=@"Rally world";
    pd.vertexFunction=[library newFunctionWithName:@"worldVertex"];pd.fragmentFunction=[library newFunctionWithName:@"worldFragment"];
    pd.colorAttachments[0].pixelFormat=MTLPixelFormatBGRA8Unorm;pd.depthAttachmentPixelFormat=MTLPixelFormatDepth32Float;
    MTLVertexDescriptor *vd=[MTLVertexDescriptor vertexDescriptor];
    vd.attributes[0].format=MTLVertexFormatFloat3;vd.attributes[0].offset=0;vd.attributes[0].bufferIndex=0;
    vd.attributes[1].format=MTLVertexFormatFloat2;vd.attributes[1].offset=12;vd.attributes[1].bufferIndex=0;
    vd.attributes[2].format=MTLVertexFormatFloat4;vd.attributes[2].offset=20;vd.attributes[2].bufferIndex=0;
    vd.attributes[3].format=MTLVertexFormatFloat3;vd.attributes[3].offset=0;vd.attributes[3].bufferIndex=2;
    vd.layouts[2].stride=12;
    vd.layouts[0].stride=sizeof(Vertex);pd.vertexDescriptor=vd;
    s.pipeline=[s.device newRenderPipelineStateWithDescriptor:pd error:&error];
    if (!s.pipeline) throw std::runtime_error(error.localizedDescription.UTF8String);
    pd.colorAttachments[0].blendingEnabled=YES;
    pd.colorAttachments[0].sourceRGBBlendFactor=MTLBlendFactorSourceAlpha;pd.colorAttachments[0].destinationRGBBlendFactor=MTLBlendFactorOneMinusSourceAlpha;
    pd.colorAttachments[0].sourceAlphaBlendFactor=MTLBlendFactorOne;pd.colorAttachments[0].destinationAlphaBlendFactor=MTLBlendFactorOneMinusSourceAlpha;
    s.blendPipeline=[s.device newRenderPipelineStateWithDescriptor:pd error:&error];if(!s.blendPipeline)throw std::runtime_error(error.localizedDescription.UTF8String);
    MTLRenderPipelineDescriptor *fp=[MTLRenderPipelineDescriptor new];
    fp.vertexFunction=[library newFunctionWithName:@"framebufferVertex"];fp.fragmentFunction=[library newFunctionWithName:@"framebufferFragment"];
    fp.colorAttachments[0].pixelFormat=MTLPixelFormatBGRA8Unorm;fp.depthAttachmentPixelFormat=MTLPixelFormatDepth32Float;
    s.framebufferPipeline=[s.device newRenderPipelineStateWithDescriptor:fp error:&error];if(!s.framebufferPipeline)throw std::runtime_error(error.localizedDescription.UTF8String);
    fp.fragmentFunction=[library newFunctionWithName:@"overlayFragment"];
    fp.colorAttachments[0].blendingEnabled=YES;
    fp.colorAttachments[0].sourceRGBBlendFactor=MTLBlendFactorOne;fp.colorAttachments[0].destinationRGBBlendFactor=MTLBlendFactorOneMinusSourceAlpha;
    fp.colorAttachments[0].sourceAlphaBlendFactor=MTLBlendFactorOne;fp.colorAttachments[0].destinationAlphaBlendFactor=MTLBlendFactorOneMinusSourceAlpha;
    s.overlayPipeline=[s.device newRenderPipelineStateWithDescriptor:fp error:&error];if(!s.overlayPipeline)throw std::runtime_error(error.localizedDescription.UTF8String);
    fp.colorAttachments[0].blendingEnabled=NO;fp.fragmentFunction=[library newFunctionWithName:@"backgroundFragment"];
    s.skyPipeline=[s.device newRenderPipelineStateWithDescriptor:fp error:&error];if(!s.skyPipeline)throw std::runtime_error(error.localizedDescription.UTF8String);
    fp.fragmentFunction=[library newFunctionWithName:@"framebufferFragment"];
    fp.depthAttachmentPixelFormat=MTLPixelFormatInvalid;
    s.presentationPipeline=[s.device newRenderPipelineStateWithDescriptor:fp error:&error];if(!s.presentationPipeline)throw std::runtime_error(error.localizedDescription.UTF8String);
    MTLDepthStencilDescriptor *dd=[MTLDepthStencilDescriptor new];dd.depthCompareFunction=MTLCompareFunctionLessEqual;dd.depthWriteEnabled=YES;s.depthState=[s.device newDepthStencilStateWithDescriptor:dd];
    dd.depthWriteEnabled=NO;s.blendDepthState=[s.device newDepthStencilStateWithDescriptor:dd];
    MTLSamplerDescriptor *sd=[MTLSamplerDescriptor new];sd.minFilter=MTLSamplerMinMagFilterLinear;sd.magFilter=MTLSamplerMinMagFilterLinear;sd.mipFilter=MTLSamplerMipFilterLinear;sd.sAddressMode=MTLSamplerAddressModeClampToEdge;sd.tAddressMode=MTLSamplerAddressModeClampToEdge;s.sampler=[s.device newSamplerStateWithDescriptor:sd];
    sd.sAddressMode=MTLSamplerAddressModeRepeat;sd.tAddressMode=MTLSamplerAddressModeRepeat;s.skySampler=[s.device newSamplerStateWithDescriptor:sd];
    if (replay) {
        NSDictionary *r=jsonFile(replay);double previous=-1;
        if (![r[@"schema"] isEqual:@"screamer-replay/v1"] || ![r[@"coordinates"] isEqual:@"game-x-left-y-up-z-back"])
            throw std::runtime_error("Unsupported replay coordinate contract");
        if(![r[@"samples"] isKindOfClass:NSArray.class]||[r[@"samples"] count]>100000)throw std::runtime_error("Invalid/oversized replay sample table");
        for (NSDictionary *sample in r[@"samples"]) {
            if(![sample isKindOfClass:NSDictionary.class]||![sample[@"camera"] isKindOfClass:NSDictionary.class])throw std::runtime_error("Invalid replay sample/camera");
            if(![sample[@"t"] isKindOfClass:NSNumber.class])throw std::runtime_error("Replay time must be numeric");
            double t=[sample[@"t"] doubleValue];NSDictionary *c=sample[@"camera"];NSArray *matrix=c[@"rotation"];
            if (!std::isfinite(t)||t<0||t<=previous||![matrix isKindOfClass:NSArray.class]||matrix.count!=9) throw std::runtime_error("Invalid replay time or camera matrix");
            simd::float3x3 rot;
            for (int col=0;col<3;col++) for (int row=0;row<3;row++) {
                if(![matrix[row*3+col] isKindOfClass:NSNumber.class])throw std::runtime_error("Camera rotation must be numeric");
                float value=[matrix[row*3+col] floatValue];
                if(!std::isfinite(value))throw std::runtime_error("Non-finite replay camera rotation");
                rot.columns[col][row]=-value;
            }
            simd::float3x3 identity=simd_transpose(rot)*rot;
            float error=0;
            for(int col=0;col<3;col++) for(int row=0;row<3;row++) error=std::max(error,fabsf(identity.columns[col][row]-(col==row ? 1.f : 0.f)));
            if (!std::isfinite(error)||error>.01f||fabsf(simd_determinant(rot)-1)>.01f)
                throw std::runtime_error("Replay camera must contain a finite orthogonal rotation");
            if (s.replay.empty()) {
                NSDictionary *p=c[@"projection"];
                if(![p isKindOfClass:NSDictionary.class])throw std::runtime_error("Invalid camera projection object");
                float values[7];NSArray *keys=@[@"width",@"height",@"fx",@"fy",@"cx",@"cy",@"near"];
                for(int n=0;n<7;n++) { if(![p[keys[n]] isKindOfClass:NSNumber.class])throw std::runtime_error("Projection must be numeric");values[n]=[p[keys[n]] floatValue];if(!std::isfinite(values[n]))throw std::runtime_error("Invalid replay projection"); }
                if(values[0]<=0||values[1]<=0||values[2]<=0||values[3]<=0||values[6]<=0)throw std::runtime_error("Invalid replay projection scale");
                s.projection={values[0],values[1],values[2],values[3],values[4],values[5],values[6]};
            }
            CameraSample frame{t,vector3(c[@"position"]),rot,{}};
            id poses=sample[@"instances"];
            if(poses&&![poses isKindOfClass:NSArray.class])throw std::runtime_error("Invalid replay instance table");
            if([poses count]>1024)throw std::runtime_error("Oversized replay instance table");
            for(NSDictionary *pose in poses){
                if(![pose isKindOfClass:NSDictionary.class]||![pose[@"id"] isKindOfClass:NSString.class])throw std::runtime_error("Invalid replay instance");
                std::string id=[pose[@"id"] UTF8String];if(frame.cars.count(id))throw std::runtime_error("Duplicate replay instance ID");
                frame.cars.emplace(id,poseFromJSON(pose));s.carPoseSamples++;
            }
            s.replay.push_back(std::move(frame));previous=t;
        }
        if (s.replay.size()<2) throw std::runtime_error("Replay requires at least two camera samples");
    }
    return self;
}
- (void)startLive:(NSString *)path input:(NSString *)input {
    State &s=*state;s.livePath=path;s.inputPath=input;s.followReplay=true;s.replay.clear();
    __weak PreviewRenderer *weakSelf=self;
    dispatch_queue_t queue=dispatch_queue_create("local.screamer.live-state-reader",DISPATCH_QUEUE_SERIAL);
    s.livePoller=dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER,0,0,queue);
    dispatch_source_set_timer(s.livePoller,DISPATCH_TIME_NOW,10*NSEC_PER_MSEC,2*NSEC_PER_MSEC);
    dispatch_source_set_event_handler(s.livePoller,^{@autoreleasepool{PreviewRenderer *r=weakSelf;if(r)[r pollLive];}});dispatch_resume(s.livePoller);
    s.inputHeartbeat=dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER,0,0,dispatch_get_main_queue());
    dispatch_source_set_timer(s.inputHeartbeat,DISPATCH_TIME_NOW,100*NSEC_PER_MSEC,10*NSEC_PER_MSEC);
    dispatch_source_set_event_handler(s.inputHeartbeat,^{PreviewRenderer *r=weakSelf;if(r)[r publishInput];});dispatch_resume(s.inputHeartbeat);
}
- (void)pollLive {
    State &s=*state;
    try{
        if(![NSFileManager.defaultManager fileExistsAtPath:s.livePath])return;
        NSDictionary *j=jsonFile(s.livePath);LiveFrame frame=liveFrameFromJSON(j,s.livePath.stringByDeletingLastPathComponent);
        std::lock_guard<std::mutex> guard(s.liveLock);
        if(!s.liveFrames.empty()&&s.liveFrames.back().epoch==frame.epoch&&s.liveFrames.back().seq>=frame.seq)return;
        if(s.liveFrames.empty()||s.liveFrames.back().epoch!=frame.epoch){s.liveFrames.clear();s.liveClockInitialized=false;}
        if(!s.liveClockInitialized){double difference=nowSeconds()-frame.publishedAt;s.liveClockOffset=fabs(difference)<5?0:difference;s.liveClockInitialized=true;}
        if(!s.liveFrames.empty()&&frame.sampleAt<s.liveFrames.back().sampleAt)throw std::runtime_error("Live sample time moved backwards");
        if(!s.liveFrames.empty()&&frame.sampleAt==s.liveFrames.back().sampleAt)s.liveFrames.back()=std::move(frame);
        else s.liveFrames.push_back(std::move(frame));
        while(s.liveFrames.size()>64)s.liveFrames.pop_front();s.liveStates++;
    }catch(const std::exception &){std::lock_guard<std::mutex> guard(s.liveLock);s.liveParseErrors++;}
}
- (void)publishInput {
    State &s=*state;if(!s.livePath||!s.inputPath||!s.liveEpoch.length)return;
    NSDictionary *j=@{@"schema":@"screamer-input/v1",@"epoch":s.liveEpoch,@"seq":@(++s.inputSeq),
        @"published_monotonic_ns":@((uint64_t)(nowSeconds()*1e9)),@"focused":@(s.inputFocused),
        @"native_renderer_ready":@(s.liveNative&&!s.originalView&&!s.sessionStopping),@"native_assets_ready":@(s.liveAssetsReady&&!s.sessionStopping),@"native_assets_epoch":s.loadedAssetsEpoch?:@"",@"native_render_requested":@(!s.originalView),
        @"pressed_keys":s.inputFocused?[[s.pressedKeys allObjects] sortedArrayUsingSelector:@selector(compare:)]:@[],@"press_counts":[s.pressCounts copy]};
    NSData *data=[NSJSONSerialization dataWithJSONObject:j options:0 error:nil];
    if(data)[data writeToFile:s.inputPath options:NSDataWritingAtomic error:nil];
}
- (void)releaseInput {
    State &s=*state;[s.pressedKeys removeAllObjects];[s.pressedCodes removeAllObjects];s.inputFocused=false;[self publishInput];
}
- (void)stopSession {
    State &s=*state;s.sessionStopping=true;[self releaseInput];
    if(s.inputHeartbeat){dispatch_source_cancel(s.inputHeartbeat);s.inputHeartbeat=nil;}
    if(s.livePoller){dispatch_source_cancel(s.livePoller);s.livePoller=nil;}
    if(s.sessionTask.running)[s.sessionTask terminate];
    if(s.sessionLog){[s.sessionLog closeFile];s.sessionLog=nil;}
}
- (void)setGameKey:(NSString *)key code:(unsigned short)code down:(BOOL)down {
    State &s=*state;if(!s.livePath||!key.length)return;NSNumber *number=@(code);
    if(down){
        if(s.pressedCodes[number])return;
        s.pressedCodes[number]=key;[s.pressedKeys addObject:key];s.pressCounts[key]=@([s.pressCounts[key] unsignedLongLongValue]+1);
    }else{
        NSString *existing=s.pressedCodes[number];if(!existing)return;[s.pressedCodes removeObjectForKey:number];
        if(![[s.pressedCodes allValues] containsObject:existing])[s.pressedKeys removeObject:existing];
    }
    [self publishInput];
}
- (void)updateFramebuffer:(const LiveFrame &)frame {
    State &s=*state;NSString *epoch=[NSString stringWithUTF8String:frame.epoch.c_str()];
    if(!frame.framePath||(frame.frameSequence==s.framebufferSeq&&[epoch isEqual:s.framebufferEpoch]))return;
    s.framebufferSeq=frame.frameSequence;s.framebufferEpoch=epoch;
    try{
        if([frame.frameFormat isEqual:@"png"]){
            NSError *error=nil;id<MTLTexture> texture=[[[MTKTextureLoader alloc] initWithDevice:s.device] newTextureWithContentsOfURL:[NSURL fileURLWithPath:frame.framePath] options:@{MTKTextureLoaderOptionSRGB:@NO,MTKTextureLoaderOptionGenerateMipmaps:@NO} error:&error];
            if(texture)s.framebufferTexture=texture;return;
        }
        NSUInteger width=frame.frameWidth,height=frame.frameHeight;
        if(!width||!height||width>4096||height>4096)throw std::runtime_error("Invalid framebuffer dimensions");
        bool rgb565=[frame.frameFormat isEqual:@"rgb565"],bgra=[frame.frameFormat isEqual:@"bgra8"];
        if(!rgb565&&!bgra&&![frame.frameFormat isEqual:@"rgba8"])throw std::runtime_error("Unsupported framebuffer format");
        NSUInteger bpp=rgb565?2:4,stride=frame.frameStride?frame.frameStride:width*bpp;
        if(stride<width*bpp||stride>65536)throw std::runtime_error("Invalid framebuffer stride");
        NSData *data=[NSData dataWithContentsOfFile:frame.framePath];if(data.length!=stride*height)throw std::runtime_error("Incomplete framebuffer file");
        std::vector<uint8_t> converted;
        const void *pixels=data.bytes;NSUInteger row=stride;
        if(rgb565){
            converted.resize(width*height*4);const uint8_t *source=(const uint8_t *)data.bytes;
            for(NSUInteger y=0;y<height;y++)for(NSUInteger x=0;x<width;x++){uint16_t pixel=source[y*stride+x*2]|source[y*stride+x*2+1]<<8;NSUInteger at=(y*width+x)*4;
                unsigned r=pixel>>11,g=(pixel>>5)&63,b=pixel&31;converted[at]=(r<<3)|(r>>2);converted[at+1]=(g<<2)|(g>>4);converted[at+2]=(b<<3)|(b>>2);converted[at+3]=255;}
            pixels=converted.data();row=width*4;
        }
        MTLPixelFormat format=bgra?MTLPixelFormatBGRA8Unorm:MTLPixelFormatRGBA8Unorm;
        auto descriptor=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:format width:width height:height mipmapped:NO];descriptor.storageMode=MTLStorageModeShared;
        id<MTLTexture> texture=[s.device newTextureWithDescriptor:descriptor];[texture replaceRegion:MTLRegionMake2D(0,0,width,height) mipmapLevel:0 withBytes:pixels bytesPerRow:row];s.framebufferTexture=texture;
    }catch(const std::exception &){std::lock_guard<std::mutex> guard(s.liveLock);s.liveParseErrors++;}
}
- (void)requestLiveAssets:(const LiveFrame &)frame {
    State &s=*state;if(frame.worldScene.empty()||s.liveAssetLoading)return;
    NSString *world=[NSString stringWithUTF8String:frame.worldScene.c_str()],*cars=frame.carsScene.empty()?nil:[NSString stringWithUTF8String:frame.carsScene.c_str()];
    NSString *assetsEpoch=[NSString stringWithUTF8String:frame.assetsEpoch.c_str()];
    if([world isEqual:s.loadedWorldScene]&&((!cars&&!s.loadedCarsScene)||[cars isEqual:s.loadedCarsScene])&&((!assetsEpoch.length&&!s.loadedAssetsEpoch.length)||[assetsEpoch isEqual:s.loadedAssetsEpoch]))return;
    if(![NSFileManager.defaultManager fileExistsAtPath:world]||nowSeconds()-s.lastAssetAttempt<1)return;s.liveAssetLoading=true;s.lastAssetAttempt=nowSeconds();
    NSString *shader=s.shaderPath;__weak PreviewRenderer *weakSelf=self;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{@autoreleasepool{
        try{
            PreviewRenderer *replacement=[[PreviewRenderer alloc] initWithScene:world shader:shader replay:nil cars:cars report:nil];
            dispatch_async(dispatch_get_main_queue(),^{PreviewRenderer *r=weakSelf;if(!r)return;State &target=*r->state;State &source=*replacement->state;
                target.vertexBuffer=source.vertexBuffer;target.indexBuffer=source.indexBuffer;target.normalBuffer=source.normalBuffer;target.reflectionTriangles=source.reflectionTriangles;target.textures=source.textures;target.batches=source.batches;target.cars=source.cars;
                target.independentParts=source.independentParts;target.vertices=source.vertices;target.triangles=source.triangles;target.carTriangles=source.carTriangles;target.center=source.center;target.radius=source.radius;
                target.loadedWorldScene=world;target.loadedCarsScene=cars;target.loadedAssetsEpoch=assetsEpoch;target.scenePath=world;target.carsPath=cars;target.liveAssetLoading=false;});
        }catch(const std::exception &){dispatch_async(dispatch_get_main_queue(),^{PreviewRenderer *r=weakSelf;if(r)r->state->liveAssetLoading=false;});}
    }});
}
- (void)updateOverlays:(const LiveFrame &)frame {
    State &s=*state;NSString *epoch=[NSString stringWithUTF8String:frame.epoch.c_str()];
    if(frame.skyPath&&![frame.skyPath isEqual:s.loadedSkyPath]){
        NSError *error=nil;MTKTextureLoader *loader=[[MTKTextureLoader alloc] initWithDevice:s.device];
        id<MTLTexture> texture=[loader newTextureWithContentsOfURL:[NSURL fileURLWithPath:frame.skyPath] options:@{MTKTextureLoaderOptionSRGB:@NO} error:&error];
        if(texture){s.skyTexture=texture;s.loadedSkyPath=frame.skyPath;}
    }
    if(frame.hudLayers.empty()){s.hudLayersReady=true;return;}
    if(frame.hudSequence==s.loadedHudSequence&&[epoch isEqual:s.hudEpoch])return;
    s.hudLayersReady=false;NSMutableArray<id<MTLTexture>> *textures=[NSMutableArray array];
    for(const auto &layer:frame.hudLayers){
        NSData *pixels=[NSData dataWithContentsOfFile:layer.path];NSUInteger width=(NSUInteger)layer.rect.width,height=(NSUInteger)layer.rect.height;
        if(pixels.length!=layer.stride*height)return;
        MTLTextureDescriptor *d=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:width height:height mipmapped:NO];d.storageMode=MTLStorageModeShared;
        id<MTLTexture> texture=[s.device newTextureWithDescriptor:d];if(!texture)return;
        [texture replaceRegion:MTLRegionMake2D(0,0,width,height) mipmapLevel:0 withBytes:pixels.bytes bytesPerRow:layer.stride];[textures addObject:texture];
    }
    s.hudTextures=textures;s.loadedHudSequence=frame.hudSequence;s.hudEpoch=epoch;s.hudLayersReady=true;
}
- (id<MTLCommandBuffer>)encodeTo:(id<MTLTexture>)target drawable:(id<CAMetalDrawable>)drawable {
    State &s=*state;double cpu=nowSeconds();dispatch_semaphore_wait(s.inFlight,DISPATCH_TIME_FOREVER);
    s.renderWidth=target.width;s.renderHeight=target.height;
    if (!s.depthTexture || s.depthTexture.width!=target.width || s.depthTexture.height!=target.height) {
        MTLTextureDescriptor *d=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatDepth32Float width:target.width height:target.height mipmapped:NO];
        d.storageMode=MTLStorageModePrivate;d.usage=MTLTextureUsageRenderTarget;s.depthTexture=[s.device newTextureWithDescriptor:d];
    }
    float aspect=(float)target.width/(float)target.height;
    std::deque<LiveFrame> liveFrames;double liveOffset=0;
    if(s.livePath){std::lock_guard<std::mutex> guard(s.liveLock);liveFrames=s.liveFrames;liveOffset=s.liveClockOffset;}
    LiveFrame latest;bool hasLive=!liveFrames.empty();std::vector<CameraSample> liveSamples;
    if(hasLive){
        latest=liveFrames.back();s.liveAge=std::max(0.0,nowSeconds()-liveOffset-latest.publishedAt);s.livePoseAge=std::max(0.0,nowSeconds()-liveOffset-latest.sampleAt);s.liveDelay=latest.period;
        NSString *epoch=[NSString stringWithUTF8String:latest.epoch.c_str()];
        if(![epoch isEqual:s.liveEpoch]){[self releaseInput];s.liveEpoch=epoch;[s.pressCounts removeAllObjects];[self publishInput];}
        [self updateFramebuffer:latest];[self updateOverlays:latest];[self requestLiveAssets:latest];
        bool assetsMatch=!latest.worldScene.empty()&&[s.loadedWorldScene isEqual:[NSString stringWithUTF8String:latest.worldScene.c_str()]];
        if(!latest.assetsEpoch.empty())assetsMatch=assetsMatch&&[s.loadedAssetsEpoch isEqual:[NSString stringWithUTF8String:latest.assetsEpoch.c_str()]];
        if(!latest.carsScene.empty())assetsMatch=assetsMatch&&[s.loadedCarsScene isEqual:[NSString stringWithUTF8String:latest.carsScene.c_str()]];
        s.liveAssetsReady=assetsMatch&&latest.hasCamera&&nativeMode(latest.mode)&&s.liveAge<.5&&s.livePoseAge<.15;
        s.liveNotice=latest.rendererNotice.empty()?nil:[NSString stringWithUTF8String:latest.rendererNotice.c_str()];
        s.livePartialHud=!latest.hudComplete&&latest.hudPrimaryValidated&&s.allowPartialHud;
        s.cullBackFaces=latest.cullBackFaces;s.diagnosticCapture=latest.diagnosticCapture;
        s.liveNative=!s.originalView&&nativeMode(latest.mode)&&latest.hasCamera&&(latest.hudComplete||s.livePartialHud||s.liveSceneOnly)&&s.hudLayersReady&&s.framebufferTexture&&assetsMatch&&s.liveAge<.5&&s.livePoseAge<.15;
        for(const auto &frame:liveFrames)if(frame.hasCamera&&nativeMode(frame.mode)&&frame.mode==latest.mode&&frame.worldScene==latest.worldScene)liveSamples.push_back(frame.pose);
        s.projection=latest.projection;if(s.liveAge>.75&&s.inputFocused)[self releaseInput];
    }else {s.liveNative=false;s.liveAssetsReady=false;}
    const auto &samples=s.livePath?liveSamples:s.replay;
    float3 eye;float4x4 rotation;simd::float3x3 properCamera=matrix_identity_float3x3;
    double elapsed=s.fixedTime>=0 ? s.fixedTime : nowSeconds()-s.started;
    size_t sampleA=0,sampleB=0;float replayAlpha=0;
    if(!samples.empty()){
        double total=samples.back().t-samples.front().t;
        double at=s.livePath?nowSeconds()-liveOffset-s.liveDelay:samples.front().t+(total>0?fmod(std::max(elapsed,0.0),total):0);
        auto upper=std::upper_bound(samples.begin(),samples.end(),at,[](double t,const CameraSample &v){return t<v.t;});
        sampleB=std::min((size_t)(upper-samples.begin()),samples.size()-1);sampleA=sampleB?sampleB-1:0;
        double span=samples[sampleB].t-samples[sampleA].t;
        replayAlpha=span<=0?0:std::clamp((float)((at-samples[sampleA].t)/span),0.f,1.f);
        if(s.livePath&&(span>.1||simd_distance(samples[sampleA].eye,samples[sampleB].eye)>3000.f))replayAlpha=1;
    }
    bool replaying=!samples.empty() && (s.livePath||s.followReplay);
    if (replaying) {
        eye=simd_mix(samples[sampleA].eye,samples[sampleB].eye,replayAlpha);
        simd::float3x3 rr=simd_matrix3x3(simd_slerp(simd_quaternion(samples[sampleA].rotation),simd_quaternion(samples[sampleB].rotation),replayAlpha));
        properCamera=rr;
        // Replay rotations include a handedness flip (-Rc^T). Interpolate Rc^T, then restore the view conversion.
        rotation=matrix_identity_float4x4;
        for (int col=0;col<3;col++) {rotation.columns[col].x=-rr.columns[col].x;rotation.columns[col].y=rr.columns[col].y;rotation.columns[col].z=rr.columns[col].z;}
    } else {
        float yaw=s.yaw+(s.animate ? (float)elapsed*0.07f : 0);
        eye=s.center+s.distance*(float3){cosf(s.pitch)*sinf(yaw),sinf(s.pitch),cosf(s.pitch)*cosf(yaw)};
        rotation=orbitRotation(eye,s.center);
    }
    float farPlane=s.radius*12.f;
    if(replaying&&!s.extendedDistance&&latest.originalDrawDistance>0)farPlane=latest.originalDrawDistance+128.f;
    s.activeFarPlane=farPlane;
    float4x4 projection=replaying ? replayProjection(s.projection,aspect,farPlane) : perspective(0.82f,aspect,std::max(16.f,s.radius/3000.f),s.radius*12.f);
    // S1 texgen uses the original, unflipped view basis and unshifted camera origin.
    // Projection's eye includes +128 along camera Z; reflection input does not.
    float4x4 reflectionView=matrix_identity_float4x4;
    for(int col=0;col<3;col++)reflectionView.columns[col]=(float4){properCamera.columns[col].x,properCamera.columns[col].y,properCamera.columns[col].z,0};
    if(!replaying)reflectionView=rotation;
    reflectionView.columns[3]=-(reflectionView*(float4){eye.x,eye.y,eye.z,0});reflectionView.columns[3].w=1;
    if(replaying)reflectionView.columns[3].z+=128.f;
    Uniforms uniforms={projection*rotation,(float4){eye.x,eye.y,eye.z,0},(float4){0,0,0,0},matrix_identity_float4x4,reflectionView,(float4){0,0,0,0}};
    std::vector<float2> carScrolls(s.cars.size(),(float2){0,0});std::vector<uint32_t> carPhases(s.cars.size(),0);
    std::vector<float4x4> carMatrices(s.cars.size(),matrix_identity_float4x4);std::vector<bool> carVisible(s.cars.size(),true);
    s.visibleCars=0;
    for(size_t index=0;index<s.cars.size();index++){
        const auto &car=s.cars[index];
        if(s.livePath&&latest.hiddenInstanceIds.count(car.id)){carVisible[index]=false;continue;}
        if(samples.empty()){carMatrices[index]=poseMatrix(car.captured,car.captured,0);carScrolls[index]=car.captured.reflectionScroll;carPhases[index]=car.captured.reflectionPhase;}
        else{
            auto a=samples[sampleA].cars.find(car.id),b=samples[sampleB].cars.find(car.id);
            if(a==samples[sampleA].cars.end()||b==samples[sampleB].cars.end()||a->second.model!=car.captured.model||b->second.model!=car.captured.model){carVisible[index]=false;continue;}
            float alpha=simd_distance(a->second.position,b->second.position)>4000.f?1.f:replayAlpha;
            carMatrices[index]=poseMatrix(a->second,b->second,alpha);carScrolls[index]=interpolatedReflectionScroll(a->second,b->second,alpha);carPhases[index]=alpha<1?a->second.reflectionPhase:b->second.reflectionPhase;
        }
        s.visibleCars++;
    }
    MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
    pass.colorAttachments[0].texture=target;pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;pass.colorAttachments[0].clearColor=MTLClearColorMake(0.26,0.42,0.58,1);
    pass.depthAttachment.texture=s.depthTexture;pass.depthAttachment.loadAction=MTLLoadActionClear;pass.depthAttachment.storeAction=MTLStoreActionDontCare;pass.depthAttachment.clearDepth=1;
    id<MTLCommandBuffer> cb=[s.queue commandBuffer];cb.label=@"Rally preview frame";
    id<MTLRenderCommandEncoder> e=[cb renderCommandEncoderWithDescriptor:pass];
    s.skyActive=false;
    if(s.liveNative&&latest.hasSky){
        [e setRenderPipelineState:s.skyPipeline];[e setDepthStencilState:nil];[e setCullMode:MTLCullModeNone];
        [e setFragmentSamplerState:s.skySampler atIndex:0];
        auto background=[&](float y,float height,float4 uv,float4 color,id<MTLTexture> texture){
            if(height<=0)return;
            FramebufferUniforms quad{(float4){0,1-2*(y+height*.5f)/target.height,1,height/target.height},uv};
            [e setVertexBytes:&quad length:sizeof(quad) atIndex:0];[e setFragmentBytes:&color length:sizeof(color) atIndex:0];[e setFragmentTexture:texture?:s.whiteTexture atIndex:0];
            [e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:6];
        };
        if(latest.skyEnabled&&s.skyTexture&&[latest.skyPath isEqual:s.loadedSkyPath]){
            float sinePitch=-properCamera.columns[1].z;
            double heading=atan2(-properCamera.columns[0].z,properCamera.columns[2].z)*2048/(2*M_PI);
            float horizon=0;float4 uv;
            if(latest.skyKind=="s1"){
                double s0=fmod((2047-heading)*.5,512);if(s0<0)s0+=512;
                double h=128*sinePitch+latest.skyCenterY-470;
                double rows=std::max(0.0,512+std::min(h,0.0)-std::max(0.0,h+512-latest.skyViewLastY));
                double extension=320*(aspect/(4.f/3.f)-1)*.5;
                horizon=std::clamp((float)(rows/400*target.height),0.f,(float)target.height);
                uv=(float4){(float)((512+s0-extension)/1536),(float)(fabs(h)*.5/256),(float)((320+2*extension)/1536),(float)(rows*.5/256)};
            }else{
                double s0=fmod(2047-heading,1024);if(s0<0)s0+=1024;s0*=.25;
                double h=128*sinePitch+s.projection.cy/1.2-470,rawBottom=511-fabs(h),bottom=std::min(rawBottom,399.0),te=std::max(0.0,(rawBottom-399)*.5);
                horizon=std::clamp((float)(bottom/400*target.height),0.f,(float)target.height);
                double extension=159*(aspect/(4.f/3.f)-1)*.5;
                uv=(float4){(float)((s0-extension)/256),(float)(fabs(h)*.5/256),(float)((159+2*extension)/256),(float)((255-te-fabs(h)*.5)/256)};
            }
            background(0,horizon,uv,(float4){0,0,0,-1},s.skyTexture);
            background(horizon,target.height-horizon,(float4){0,0,1,1},(float4){latest.skyGround.x,latest.skyGround.y,latest.skyGround.z,1},nil);s.skyActive=true;
        }else background(0,target.height,(float4){0,0,1,1},(float4){latest.skyFlat.x,latest.skyFlat.y,latest.skyFlat.z,1},nil);
    }
    [e setRenderPipelineState:s.pipeline];[e setDepthStencilState:s.depthState];[e setFrontFacingWinding:MTLWindingClockwise];[e setCullMode:s.cullBackFaces?MTLCullModeBack:MTLCullModeNone];
    s.reflectionDraws=0;
    [e setVertexBuffer:s.normalBuffer offset:0 atIndex:2];[e setVertexBuffer:s.vertexBuffer offset:0 atIndex:0];[e setVertexBytes:&uniforms length:sizeof(uniforms) atIndex:1];[e setFragmentSamplerState:s.sampler atIndex:0];
    auto drawBatch=[&](const Batch &b){
        if(b.instance>=0&&!carVisible[(size_t)b.instance])return;
        NSInteger texture=reflectionTexture(b,b.instance>=0?carPhases[(size_t)b.instance]:0);
        BOOL textured=texture>=0 && texture<(NSInteger)s.textures.count;
        uniforms.options.x=textured ? 1.f : 0.f;uniforms.options.y=b.alphaTest;uniforms.options.z=b.blend?1.f:0.f;uniforms.options.w=b.s1Reflection?1.f:0.f;
        float2 scroll=b.instance>=0?carScrolls[(size_t)b.instance]:(float2){0,0};uniforms.reflectionScroll=(float4){scroll.x,scroll.y,0,0};
        if(b.s1Reflection)s.reflectionDraws++;
        uniforms.model=b.instance>=0?carMatrices[(size_t)b.instance]:matrix_identity_float4x4;
        // Source-authored zero/folded-normal exceptions retain their previous
        // two-sided rendering without disabling culling for the rest of a material.
        [e setCullMode:s.cullBackFaces&&!b.doubleSided?MTLCullModeBack:MTLCullModeNone];
        [e setRenderPipelineState:b.blend?s.blendPipeline:s.pipeline];[e setDepthStencilState:b.blend?s.blendDepthState:s.depthState];
        [e setVertexBytes:&uniforms length:sizeof(uniforms) atIndex:1];
        [e setFragmentBytes:&uniforms length:sizeof(uniforms) atIndex:1];
        [e setFragmentSamplerState:b.s1Reflection?s.skySampler:s.sampler atIndex:0];
        [e setFragmentTexture:textured ? s.textures[(NSUInteger)texture] : s.whiteTexture atIndex:0];
        [e drawIndexedPrimitives:MTLPrimitiveTypeTriangle indexCount:b.count indexType:MTLIndexTypeUInt32 indexBuffer:s.indexBuffer indexBufferOffset:(NSUInteger)b.first*4];
    };
    if(!s.livePath||s.liveNative)for(const Batch &b:s.batches)if(!b.blend)drawBatch(b);
    std::vector<const Batch *> transparent;
    if(!s.livePath||s.liveNative)for(const Batch &b:s.batches)if(b.blend&&(b.instance<0||carVisible[(size_t)b.instance]))transparent.push_back(&b);
    auto depth=[&](const Batch *b){float4 local={b->center.x,b->center.y,b->center.z,1};float3 world=b->instance>=0?(carMatrices[(size_t)b->instance]*local).xyz:b->center;float3 delta=world-eye;return simd_length_squared(delta);};
    std::sort(transparent.begin(),transparent.end(),[&](const Batch *a,const Batch *b){return depth(a)>depth(b);});
    for(const Batch *b:transparent)drawBatch(*b);
    if(s.livePath&&s.framebufferTexture){
        [e setRenderPipelineState:s.framebufferPipeline];[e setDepthStencilState:nil];[e setCullMode:MTLCullModeNone];[e setFragmentTexture:s.framebufferTexture atIndex:0];
        float sourceW=s.framebufferTexture.width,sourceH=s.framebufferTexture.height,w=target.width,h=target.height;
        auto quad=[&](float x,float y,float width,float height,float4 uv){
            FramebufferUniforms f{(float4){2*(x+width*.5f)/w-1,1-2*(y+height*.5f)/h,width/w,height/h},uv};
            [e setVertexBytes:&f length:sizeof(f) atIndex:0];[e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:6];
        };
        auto rectangle=[&](float x,float y,float width,float height,float sx,float sy,float sw,float sh){quad(x,y,width,height,(float4){sx/sourceW,sy/sourceH,sw/sourceW,sh/sourceH});};
        if(s.liveNative&&!s.liveSceneOnly){float scale=h/sourceH;for(const auto &rect:latest.hud){float x=rect.x*scale;if(rect.anchor=="right")x=w-(sourceW-rect.x)*scale;else if(rect.anchor=="center")x=w*.5f+(rect.x-sourceW*.5f)*scale;
            if(rect.anchor=="stretch")x=0;
            rectangle(x,rect.y*scale,rect.anchor=="stretch"?w:rect.width*scale,rect.height*scale,rect.x,rect.y,rect.width,rect.height);}
            [e setRenderPipelineState:s.overlayPipeline];
            for(size_t n=0;n<latest.hudLayers.size();n++){const auto &layer=latest.hudLayers[n];const auto &rect=layer.rect;float x=rect.x*scale;
                if(rect.anchor=="right")x=w-(sourceW-rect.x)*scale;else if(rect.anchor=="center")x=w*.5f+(rect.x-sourceW*.5f)*scale;
                if(rect.anchor=="stretch")x=0;
                [e setFragmentTexture:s.hudTextures[n] atIndex:0];quad(x,rect.y*scale,rect.anchor=="stretch"?w:rect.width*scale,rect.height*scale,(float4){0,0,1,1});}}
        else if(!s.liveNative){float scale=std::min(w/sourceW,h/sourceH);rectangle((w-sourceW*scale)*.5f,(h-sourceH*scale)*.5f,sourceW*scale,sourceH*scale,0,0,sourceW,sourceH);}
    }
    [e endEncoding];
    if(drawable&&target!=drawable.texture){
        MTLRenderPassDescriptor *output=[MTLRenderPassDescriptor renderPassDescriptor];
        output.colorAttachments[0].texture=drawable.texture;output.colorAttachments[0].loadAction=MTLLoadActionClear;
        output.colorAttachments[0].storeAction=MTLStoreActionStore;output.colorAttachments[0].clearColor=MTLClearColorMake(0,0,0,1);
        id<MTLRenderCommandEncoder> presentation=[cb renderCommandEncoderWithDescriptor:output];
        [presentation setRenderPipelineState:s.presentationPipeline];[presentation setFragmentTexture:target atIndex:0];
        [presentation setFragmentSamplerState:s.sampler atIndex:0];
        float renderAspect=(float)target.width/target.height,displayAspect=(float)drawable.texture.width/drawable.texture.height;
        FramebufferUniforms destination{(float4){0,0,std::min(1.f,renderAspect/displayAspect),std::min(1.f,displayAspect/renderAspect)},(float4){0,0,1,1}};
        [presentation setVertexBytes:&destination length:sizeof(destination) atIndex:0];
        [presentation drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:6];[presentation endEncoding];
    }
    if (drawable) {
        __weak PreviewRenderer *weakSelf=self;
        const uint64_t generation=s.foregroundGeneration.load();const bool wasForeground=s.foreground.load();
        [drawable addPresentedHandler:^(id<MTLDrawable> d) {
            PreviewRenderer *strongSelf=weakSelf;if (!strongSelf) return;
            std::lock_guard<std::mutex> guard(strongSelf->state->metricsLock);
            if (d.presentedTime>0) strongSelf->state->presentedTimes.push_back(d.presentedTime);
            State &present=*strongSelf->state;
            if(wasForeground&&present.foreground.load()&&generation==present.foregroundGeneration.load()&&d.presentedTime>0){
                if(generation!=present.lastForegroundGeneration){present.lastForegroundGeneration=generation;present.lastForegroundPresent=0;}
                if(d.presentedTime>present.lastForegroundPresent){
                    if(present.lastForegroundPresent>0)present.foregroundIntervals.push_back((d.presentedTime-present.lastForegroundPresent)*1000);
                    present.lastForegroundPresent=d.presentedTime;present.foregroundPresented++;
                }
            }
        }];
        [cb presentDrawable:drawable];
    }
    double encoded=(nowSeconds()-cpu)*1000;
    __weak PreviewRenderer *weakSelf=self;
    [cb addCompletedHandler:^(id<MTLCommandBuffer> completed) {
        PreviewRenderer *strongSelf=weakSelf;
        if (strongSelf) {
            State &ss=*strongSelf->state;std::lock_guard<std::mutex> guard(ss.metricsLock);
            if (completed.status==MTLCommandBufferStatusCompleted && completed.GPUEndTime>=completed.GPUStartTime) ss.gpuMs.push_back((completed.GPUEndTime-completed.GPUStartTime)*1000);
            if(completed.status==MTLCommandBufferStatusError){ss.gpuErrors++;ss.lastGpuError=completed.error.localizedDescription;if(ss.gpuErrors==1)fprintf(stderr,"Metal frame failed: %s\n",ss.lastGpuError.UTF8String);}
            ss.encodeMs.push_back(encoded);dispatch_semaphore_signal(ss.inFlight);
        }
    }];
    if(s.livePath){if(s.liveNative)s.nativeFrames++;else s.fallbackFrames++;}
    s.frames++;[cb commit];return cb;
}
- (void)drawInMTKView:(MTKView *)view {
    @autoreleasepool {
        double begin=nowSeconds();id<CAMetalDrawable> d=view.currentDrawable;
        [self renderDrawable:d inView:view callbackAt:begin drawableWait:(nowSeconds()-begin)*1000];
    }
}
- (void)setForeground:(BOOL)active {
    if(state->foreground.exchange(active)!=bool(active))state->foregroundGeneration.fetch_add(1);
}
- (void)renderDrawable:(id<CAMetalDrawable>)d inView:(MTKView *)view callbackAt:(double)begin drawableWait:(double)wait {
    @autoreleasepool {
        {std::lock_guard<std::mutex> guard(state->metricsLock);state->drawTimes.push_back(begin);state->drawableWaitMs.push_back(wait);}
        CGSize expected=synchronizeGameDrawable(view);
        NSSize points=[view convertRect:view.bounds toView:nil].size;
        state->windowContentWidth=points.width;state->windowContentHeight=points.height;
        state->viewBoundsSize=view.bounds.size;state->viewFrameSize=view.frame.size;state->viewBackingSize=expected;state->viewDrawableSize=view.drawableSize;
        state->layerBoundsSize=view.layer.bounds.size;state->layerDrawableSize=((CAMetalLayer *)view.layer).drawableSize;
        state->windowLayoutSize=view.window.contentLayoutRect.size;state->fullScreen=(view.window.styleMask&NSWindowStyleMaskFullScreen)!=0;
        if (!d) return;
        state->drawableWidth=d.texture.width;state->drawableHeight=d.texture.height;
        if(d.texture.width!=(NSUInteger)expected.width||d.texture.height!=(NSUInteger)expected.height){state->staleDrawableDrops++;return;}
        id<MTLTexture> target=d.texture;
        if(state->render4K){
            NSUInteger width=state->widescreen?3840:2880;
            if(!state->render4KTexture||state->render4KTexture.width!=width){
                MTLTextureDescriptor *description=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:width height:2160 mipmapped:NO];
                description.storageMode=MTLStorageModePrivate;description.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;
                state->render4KTexture=[state->device newTextureWithDescriptor:description];
            }
            target=state->render4KTexture;
        }else if(state->livePath){
            NSUInteger ax=state->widescreen?16:4,ay=state->widescreen?9:3;
            NSUInteger units=std::max((NSUInteger)1,std::min(d.texture.width/ax,d.texture.height/ay));
            NSUInteger width=units*ax,height=units*ay;
            if(width!=d.texture.width||height!=d.texture.height){
                if(!state->widescreenTexture||state->widescreenTexture.width!=width||state->widescreenTexture.height!=height){
                    MTLTextureDescriptor *description=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:width height:height mipmapped:NO];
                    description.storageMode=MTLStorageModePrivate;description.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;
                    state->widescreenTexture=[state->device newTextureWithDescriptor:description];
                }
                target=state->widescreenTexture;
            }
        }
        [self encodeTo:target drawable:d];
        if(state->livePath){
            NSTextField *label=(NSTextField *)[view viewWithTag:701];NSString *message=nil;
            if(state->startupError.length)message=state->startupError;
            else if(!state->framebufferTexture&&!state->liveNative)message=[NSString stringWithFormat:@"Starting %@…",applicationTitle()];
            else if(state->liveAge>.75)message=[NSString stringWithFormat:@"Reconnecting to %@…",applicationTitle()];
            if(!message&&state->liveNative&&state->liveSceneOnly)message=@"Diagnostic view: original overlays hidden";
            label.hidden=!message.length;if(message)label.stringValue=message;
            NSTextField *partial=(NSTextField *)[view viewWithTag:702];
            BOOL partialActive=state->liveNative&&state->livePartialHud&&!state->liveSceneOnly;
            partial.hidden=!(partialActive||(!state->liveNative&&!state->originalView&&state->liveNotice.length));
            partial.stringValue=partialActive?@"Experimental Metal view · some overlays unavailable":state->liveNotice?:@"";
        }
        if (nowSeconds()-state->lastTitle>1) {
            state->lastTitle=nowSeconds();NSDictionary *m=[self metrics];
            NSString *title=state->livePath?applicationTitle():state->sceneName;
            if(state->livePath&&!state->liveNative)view.window.title=[NSString stringWithFormat:@"%@ — Original view",title];
            else view.window.title=[NSString stringWithFormat:@"%@ — Metal • %.1f FPS • %lux%lu",title,[m[@"presented_fps"] doubleValue],(unsigned long)state->renderWidth,(unsigned long)state->renderHeight];
            if(state->livePath&&state->reportPath)[self writeReport];
        }
    }
}
- (void)mtkView:(MTKView *)view drawableSizeWillChange:(CGSize)size {(void)view;(void)size;}
- (NSDictionary *)metrics {
    State &s=*state;std::lock_guard<std::mutex> guard(s.metricsLock);
    std::vector<double> intervals;auto times=s.presentedTimes;std::sort(times.begin(),times.end());
    times.erase(std::unique(times.begin(),times.end()),times.end());
    for (size_t i=1;i<times.size();i++) if (times[i]>times[i-1]) intervals.push_back((times[i]-times[i-1])*1000);
    double fps=times.size()>1 ? (times.size()-1)/(times.back()-times.front()) : 0;
    double gpu=0;for (double x:s.gpuMs)gpu+=x;if (!s.gpuMs.empty())gpu/=s.gpuMs.size();
    NSMutableDictionary *result=[@{@"scene":s.scenePath,@"device":s.device.name,@"drawable_width":@(s.renderWidth),@"drawable_height":@(s.renderHeight),@"submitted_frames":@(s.frames),@"native_world_frames":@(s.nativeFrames),@"original_fallback_frames":@(s.fallbackFrames),@"presented_frames":@(times.size()),@"presented_fps":@(fps),@"present_interval_p50_ms":@(percentile(intervals,.5)),@"present_interval_p95_ms":@(percentile(intervals,.95)),@"gpu_mean_ms":@(gpu),@"gpu_p95_ms":@(percentile(s.gpuMs,.95)),@"cpu_encode_p95_ms":@(percentile(s.encodeMs,.95)),@"vertices":@(s.vertices),@"triangles":@(s.triangles),@"draw_batches":@(s.batches.size()),@"textures":@(s.textures.count),@"replay_camera_samples":@(s.replay.size()),@"cars":@(s.cars.size()),@"visible_cars":@(s.visibleCars),@"car_triangles":@(s.carTriangles),@"replay_instance_samples":@(s.carPoseSamples),@"car_pose_source":s.replay.empty()?@"captured fixed poses":@"recorded id+model-guarded root poses; position lerp and quaternion slerp",@"car_limitations":@"frozen wheel/part poses; approximate reflection UV; batch-sorted transparency",@"physics_execution":@"none: viewer reads captured game geometry/camera poses",@"render_target_fps":@60} mutableCopy];
    if(s.independentParts){result[@"dynamic_part_instances"]=@(s.cars.size());result[@"cars"]=NSNull.null;result[@"car_limitations"]=@"live independent actor-part transforms; authored A0 window reflections; E0 palette-effect shadows omitted; texture damage/animation frames frozen";}
    result[@"window_content_width"]=@(s.windowContentWidth);result[@"window_content_height"]=@(s.windowContentHeight);
    result[@"view_frame_width"]=@(s.viewFrameSize.width);result[@"view_frame_height"]=@(s.viewFrameSize.height);
    result[@"view_bounds_width"]=@(s.viewBoundsSize.width);result[@"view_bounds_height"]=@(s.viewBoundsSize.height);
    result[@"view_backing_width"]=@(s.viewBackingSize.width);result[@"view_backing_height"]=@(s.viewBackingSize.height);
    result[@"view_drawable_width"]=@(s.viewDrawableSize.width);result[@"view_drawable_height"]=@(s.viewDrawableSize.height);
    result[@"layer_bounds_width"]=@(s.layerBoundsSize.width);result[@"layer_bounds_height"]=@(s.layerBoundsSize.height);
    result[@"layer_drawable_width"]=@(s.layerDrawableSize.width);result[@"layer_drawable_height"]=@(s.layerDrawableSize.height);
    result[@"window_layout_width"]=@(s.windowLayoutSize.width);result[@"window_layout_height"]=@(s.windowLayoutSize.height);
    result[@"fullscreen"]=@(s.fullScreen);result[@"stale_drawable_drops"]=@(s.staleDrawableDrops);
    if(s.drawableWidth&&s.drawableHeight&&s.windowContentHeight&&s.renderHeight)
        result[@"presented_scene_aspect_ratio"]=@(((double)s.renderWidth/s.renderHeight)*(s.windowContentWidth/s.windowContentHeight)/((double)s.drawableWidth/s.drawableHeight));
    result[@"s1_reflection_triangles"]=@(s.reflectionTriangles);result[@"s1_reflection_batches_drawn"]=@(s.reflectionDraws);
    result[@"sky_active"]=@(s.skyActive);result[@"hud_alpha_layers"]=@(s.hudTextures.count);result[@"backface_culling"]=@(s.cullBackFaces);result[@"game_aspect_ratio"]=s.renderHeight?@((double)s.renderWidth/s.renderHeight):@0;
    result[@"original_game_view_selected"]=@(s.originalView);result[@"partial_hud_opt_in"]=@(s.allowPartialHud);result[@"hud_coverage"]=s.liveNative&&s.livePartialHud?@"primary-instruments-only":@"complete-or-not-active";result[@"gpu_errors"]=@(s.gpuErrors);if(s.lastGpuError)result[@"last_gpu_error"]=s.lastGpuError;result[@"render_width"]=@(s.renderWidth);result[@"render_height"]=@(s.renderHeight);result[@"render_4k_selected"]=@(s.render4K);result[@"widescreen_selected"]=@(s.widescreen);result[@"extended_distance_selected"]=@(s.extendedDistance);result[@"active_far_plane"]=@(s.activeFarPlane);if(s.drawableWidth){result[@"drawable_width"]=@(s.drawableWidth);result[@"drawable_height"]=@(s.drawableHeight);}
    if(s.livePath){std::lock_guard<std::mutex> liveGuard(s.liveLock);result[@"live_states"]=@(s.liveStates);result[@"live_parse_errors"]=@(s.liveParseErrors);result[@"live_state_age_ms"]=@(s.liveAge*1000);result[@"live_pose_age_ms"]=@(s.livePoseAge*1000);result[@"interpolation_delay_ms"]=@(s.liveDelay*1000);result[@"diagnostic_live_scene_only"]=@(s.liveSceneOnly);result[@"presentation_mode"]=s.liveNative?(s.liveSceneOnly?@"native-scene-only-diagnostic":@"native-world-with-original-HUD"):@"original-framebuffer-fallback";result[@"input_published_sequence"]=@(s.inputSeq);result[@"car_pose_source"]=@"live atomic game snapshots; id+model guards; delayed position/quaternion interpolation";result[@"physics_execution"]=@"external DOSBox game runtime; renderer never advances physics";}
    if(s.diagnosticCapture){result[@"diagnostic_capture_replay"]=@YES;result[@"physics_execution"]=@"none: immutable captured pose used for diagnostic comparison";}
    result[@"draw_callbacks"]=@(s.drawTimes.size());
    result[@"draw_callback_hz"]=@(s.drawTimes.size()>1?(s.drawTimes.size()-1)/(s.drawTimes.back()-s.drawTimes.front()):0);
    result[@"drawable_wait_p95_ms"]=@(percentile(s.drawableWaitMs,.95));
    double foregroundMs=0;for(double interval:s.foregroundIntervals)foregroundMs+=interval;
    result[@"foreground_presented_frames"]=@(s.foregroundPresented);
    result[@"foreground_presented_fps"]=@(foregroundMs>0?s.foregroundIntervals.size()*1000/foregroundMs:0);
    result[@"foreground_present_interval_p95_ms"]=@(percentile(s.foregroundIntervals,.95));
    result[@"display_scheduler"]=s.displayScheduler;
    result[@"display_target_hz"]=@(s.displayTargetTimes.size()>1?(s.displayTargetTimes.size()-1)/(s.displayTargetTimes.back()-s.displayTargetTimes.front()):0);
    return result;
}
- (void)writeReport {
    NSDictionary *m=[self metrics];NSData *d=[NSJSONSerialization dataWithJSONObject:m options:NSJSONWritingPrettyPrinted error:nil];
    if (state->reportPath) [d writeToFile:state->reportPath atomically:YES];
    fprintf(stdout,"%s\n",[[[NSString alloc] initWithData:d encoding:NSUTF8StringEncoding] UTF8String]);
}
@end

API_AVAILABLE(macos(14.0))
@interface MetalDisplayDriver:NSObject<CAMetalDisplayLinkDelegate>
@property(nonatomic,strong)CAMetalDisplayLink *link;
@property(nonatomic,weak)MTKView *view;
@property(nonatomic,weak)PreviewRenderer *renderer;
- (instancetype)initWithView:(MTKView *)view renderer:(PreviewRenderer *)renderer;
- (void)stop;
@end
@implementation MetalDisplayDriver
- (instancetype)initWithView:(MTKView *)view renderer:(PreviewRenderer *)renderer {
    self=[super init];if(!self)return nil;
    if(![view.layer isKindOfClass:CAMetalLayer.class])return nil;
    self.view=view;self.renderer=renderer;CAMetalLayer *layer=(CAMetalLayer *)view.layer;
    layer.presentsWithTransaction=NO;layer.displaySyncEnabled=YES;layer.maximumDrawableCount=3;
    self.link=[[CAMetalDisplayLink alloc] initWithMetalLayer:layer];self.link.delegate=self;
    self.link.preferredFrameRateRange=CAFrameRateRangeMake(60,60,60);self.link.preferredFrameLatency=1;
    renderer->state->displayScheduler=@"CAMetalDisplayLink-60";
    [self.link addToRunLoop:NSRunLoop.mainRunLoop forMode:NSRunLoopCommonModes];self.link.paused=NO;
    return self;
}
- (void)metalDisplayLink:(CAMetalDisplayLink *)link needsUpdate:(CAMetalDisplayLinkUpdate *)update {
    (void)link;@autoreleasepool{
        double begin=nowSeconds();PreviewRenderer *renderer=self.renderer;MTKView *view=self.view;if(!renderer||!view)return;
        {std::lock_guard<std::mutex> guard(renderer->state->metricsLock);auto &times=renderer->state->displayTargetTimes;
            if(update.targetPresentationTimestamp>0&&(times.empty()||update.targetPresentationTimestamp>times.back()))times.push_back(update.targetPresentationTimestamp);}
        // The display link supplies the drawable. Never ask MTKView/currentDrawable
        // or CAMetalLayer/nextDrawable from this path.
        [renderer renderDrawable:update.drawable inView:view callbackAt:begin drawableWait:0];
    }
}
- (void)stop {[self.link invalidate];self.link=nil;}
@end

static NSString *gameKey(NSEvent *event) {
    switch(event.keyCode){
        case 126:return @"up";case 125:return @"down";case 123:return @"left";case 124:return @"right";
        case 36:case 76:return @"enter";case 53:return @"escape";case 49:return @"space";case 48:return @"tab";case 51:return @"backspace";
        case 56:return @"lshift";case 60:return @"rshift";case 59:case 62:return @"ctrl";case 58:case 61:return @"alt";
        case 122:return @"f1";case 120:return @"f2";case 99:return @"f3";case 118:return @"f4";case 96:return @"f5";case 97:return @"f6";
        case 98:return @"f7";case 100:return @"f8";case 101:return @"f9";case 109:return @"f10";case 103:return @"f11";case 111:return @"f12";
    }
    NSString *text=event.charactersIgnoringModifiers.lowercaseString;
    if(text.length==1){unichar c=[text characterAtIndex:0];if((c>='a'&&c<='z')||(c>='0'&&c<='9'))return text;}
    return nil;
}
@interface PreviewView:MTKView
@end
@implementation PreviewView
- (BOOL)acceptsFirstResponder {return YES;}
- (void)setFrameSize:(NSSize)size {[super setFrameSize:size];synchronizeGameDrawable(self);}
- (void)setBoundsSize:(NSSize)size {[super setBoundsSize:size];synchronizeGameDrawable(self);}
- (void)viewDidMoveToWindow {[super viewDidMoveToWindow];synchronizeGameDrawable(self);}
- (void)layout {
    [super layout];
    synchronizeGameDrawable(self);
}
- (void)viewDidChangeBackingProperties {
    [super viewDidChangeBackingProperties];
    synchronizeGameDrawable(self);
}
- (void)keyDown:(NSEvent *)event {
    PreviewRenderer *r=(PreviewRenderer *)self.delegate;
    if(r->state->livePath){if(event.modifierFlags&NSEventModifierFlagCommand){[super keyDown:event];return;}r->state->inputFocused=true;if(!event.isARepeat)[r setGameKey:gameKey(event) code:event.keyCode down:YES];return;}
    if (!event.charactersIgnoringModifiers.length)return;
    State &s=*r->state;unichar key=[event.charactersIgnoringModifiers characterAtIndex:0];
    if(key==NSLeftArrowFunctionKey)s.yaw-=.12f;
    else if(key==NSRightArrowFunctionKey)s.yaw+=.12f;
    else if(key==NSUpArrowFunctionKey)s.pitch=std::min(s.pitch+.06f,1.48f);
    else if(key==NSDownArrowFunctionKey)s.pitch=std::max(s.pitch-.06f,.05f);
    else if(key==' ') {s.yaw+=(s.animate ? (float)(nowSeconds()-s.started)*.07f : 0);s.started=nowSeconds();s.animate=!s.animate;}
    else if(key=='r'||key=='R'){s.distance=s.radius*1.65f;s.pitch=.85f;s.yaw=.5f;s.started=nowSeconds();}
    else if(key=='c'||key=='C')s.followReplay=!s.followReplay;
    else [super keyDown:event];
}
- (void)keyUp:(NSEvent *)event {
    PreviewRenderer *r=(PreviewRenderer *)self.delegate;if(r->state->livePath){[r setGameKey:r->state->pressedCodes[@(event.keyCode)]?:gameKey(event) code:event.keyCode down:NO];return;}[super keyUp:event];
}
- (void)flagsChanged:(NSEvent *)event {
    PreviewRenderer *r=(PreviewRenderer *)self.delegate;if(r->state->livePath){NSString *key=gameKey(event);if(key){BOOL down=r->state->pressedCodes[@(event.keyCode)]==nil;[r setGameKey:key code:event.keyCode down:down];}return;}[super flagsChanged:event];
}
- (void)scrollWheel:(NSEvent *)event {
    PreviewRenderer *r=(PreviewRenderer *)self.delegate;State &s=*r->state;
    if(s.livePath)return;
    s.distance=std::clamp(s.distance*expf((float)event.scrollingDeltaY*.025f),s.radius*.02f,s.radius*8.f);
}
@end
@interface PreviewApp:NSObject<NSApplicationDelegate,NSWindowDelegate>
@property(nonatomic,strong)NSWindow *window;
@property(nonatomic,strong)PreviewRenderer *renderer;
@property(nonatomic,strong)id displayDriver;
- (void)installMenus;
@end
@implementation PreviewApp
- (void)fitInitialGameWindow {
    // Screen metadata can be unavailable until orderFront. Fit the actual
    // constrained content, rather than keeping an independently clamped width.
    if(self.window.styleMask&NSWindowStyleMaskFullScreen)return;
    NSSize current=self.window.contentView.bounds.size;
    if(current.width<=0||current.height<=0)return;
    CGFloat aspect=self.renderer->state->widescreen?16.0/9.0:4.0/3.0;
    CGFloat width=std::min(current.width,current.height*aspect),height=width/aspect;
    if(fabs(current.width/current.height-aspect)>.002){
        self.window.contentMinSize=NSMakeSize(std::min((CGFloat)640,width),std::min((CGFloat)(640/aspect),height));
        [self.window setContentSize:NSMakeSize(width,height)];
    }
}
- (void)renderOriginalGame:(NSMenuItem *)item {
    self.renderer->state->originalView=true;self.renderer->state->liveNative=false;[self.renderer publishInput];
    for(NSMenuItem *sibling in item.menu.itemArray)sibling.state=sibling==item?NSControlStateValueOn:NSControlStateValueOff;
}
- (void)renderAtWindowResolution:(NSMenuItem *)item {
    self.renderer->state->render4K=false;self.renderer->state->originalView=false;
    for(NSMenuItem *sibling in item.menu.itemArray)sibling.state=sibling==item?NSControlStateValueOn:NSControlStateValueOff;
}
- (void)renderAt4K:(NSMenuItem *)item {
    self.renderer->state->render4K=true;self.renderer->state->originalView=false;
    for(NSMenuItem *sibling in item.menu.itemArray)sibling.state=sibling==item?NSControlStateValueOn:NSControlStateValueOff;
}
- (void)installMenus {
    NSMenu *menu=[NSMenu new],*appMenu=[NSMenu new];NSMenuItem *item=[NSMenuItem new];
    [appMenu addItemWithTitle:[@"Quit " stringByAppendingString:applicationTitle()] action:@selector(terminate:) keyEquivalent:@"q"];item.submenu=appMenu;[menu addItem:item];NSApp.mainMenu=menu;
    if(!self.renderer->state->bundledGameUI){
        NSMenu *renderMenu=[[NSMenu alloc] initWithTitle:@"Rendering"];NSMenuItem *renderRoot=[NSMenuItem new];renderRoot.title=@"Rendering";renderRoot.submenu=renderMenu;[menu addItem:renderRoot];
        NSMenuItem *windowResolution=[renderMenu addItemWithTitle:@"Window Resolution" action:@selector(renderAtWindowResolution:) keyEquivalent:@""];windowResolution.target=self;
        NSMenuItem *resolution4K=[renderMenu addItemWithTitle:self.renderer->state->widescreen?@"4K (3840 × 2160)":@"2160p (2880 × 2160)" action:@selector(renderAt4K:) keyEquivalent:@""];resolution4K.target=self;
        windowResolution.state=self.renderer->state->render4K?NSControlStateValueOff:NSControlStateValueOn;
        resolution4K.state=self.renderer->state->render4K?NSControlStateValueOn:NSControlStateValueOff;
        NSMenuItem *original=[renderMenu addItemWithTitle:@"Original Game View" action:@selector(renderOriginalGame:) keyEquivalent:@""];original.target=self;
    }
}
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    (void)notification;[self installMenus];
    self.window=[[NSWindow alloc] initWithContentRect:NSMakeRect(0,0,1280,720) styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable|NSWindowStyleMaskResizable|NSWindowStyleMaskMiniaturizable backing:NSBackingStoreBuffered defer:NO];
    self.window.title=applicationTitle();self.window.delegate=self;
    CGFloat aspect=self.renderer->state->widescreen?16.0/9.0:4.0/3.0;
    self.window.contentMinSize=NSMakeSize(640,640/aspect);self.window.contentAspectRatio=NSMakeSize(aspect,1);
    self.window.collectionBehavior=NSWindowCollectionBehaviorFullScreenPrimary;
    NSScreen *initialScreen=self.window.screen?:NSScreen.screens.firstObject;
    NSRect available=initialScreen.visibleFrame;
    if(available.size.width>0&&available.size.height>0){
        NSRect content=[self.window contentRectForFrameRect:available];
        CGFloat width=std::min((CGFloat)1280,content.size.width*.9),height=width/aspect;
        if(height>content.size.height*.9){height=content.size.height*.9;width=height*aspect;}
        [self.window setContentSize:NSMakeSize(width,height)];
    }
    PreviewView *view=[[PreviewView alloc] initWithFrame:self.window.contentView.bounds device:self.renderer->state->device];
    view.autoResizeDrawable=NO;view.autoresizingMask=NSViewWidthSizable|NSViewHeightSizable;view.colorPixelFormat=MTLPixelFormatBGRA8Unorm;view.depthStencilPixelFormat=MTLPixelFormatInvalid;view.preferredFramesPerSecond=60;view.delegate=self.renderer;view.enableSetNeedsDisplay=NO;view.paused=YES;
    self.window.contentView=view;[self.window center];[self.window makeKeyAndOrderFront:nil];[self.window makeFirstResponder:view];if (@available(macOS 14.0,*)) [NSApp activate]; else [NSApp activateIgnoringOtherApps:YES];
    if(self.renderer->state->livePath){
        NSTextField *label=[NSTextField wrappingLabelWithString:[NSString stringWithFormat:@"Starting %@…",applicationTitle()]];label.tag=701;label.alignment=NSTextAlignmentCenter;label.font=[NSFont systemFontOfSize:18 weight:NSFontWeightMedium];label.textColor=NSColor.whiteColor;label.drawsBackground=YES;label.backgroundColor=[NSColor colorWithWhite:.1 alpha:.92];label.translatesAutoresizingMaskIntoConstraints=NO;[view addSubview:label];
        NSLayoutConstraint *desiredWidth=[label.widthAnchor constraintLessThanOrEqualToAnchor:view.widthAnchor multiplier:.85];desiredWidth.priority=NSLayoutPriorityDefaultHigh;
        [NSLayoutConstraint activateConstraints:@[[label.centerXAnchor constraintEqualToAnchor:view.centerXAnchor],[label.centerYAnchor constraintEqualToAnchor:view.centerYAnchor],[label.widthAnchor constraintLessThanOrEqualToConstant:560],desiredWidth,[label.heightAnchor constraintGreaterThanOrEqualToConstant:64]]];
        NSTextField *partial=[NSTextField labelWithString:@"Experimental Metal view · some overlays unavailable"];partial.tag=702;partial.hidden=YES;partial.font=[NSFont systemFontOfSize:12];partial.textColor=NSColor.whiteColor;partial.drawsBackground=YES;partial.backgroundColor=[NSColor colorWithWhite:.08 alpha:.85];partial.translatesAutoresizingMaskIntoConstraints=NO;[view addSubview:partial];
        [NSLayoutConstraint activateConstraints:@[[partial.leadingAnchor constraintEqualToAnchor:view.leadingAnchor constant:12],[partial.bottomAnchor constraintEqualToAnchor:view.bottomAnchor constant:-12]]];
    }
    [self fitInitialGameWindow];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,250*NSEC_PER_MSEC),dispatch_get_main_queue(),^{[self fitInitialGameWindow];});
    synchronizeGameDrawable(view);
    if(@available(macOS 14.0,*))self.displayDriver=[[MetalDisplayDriver alloc] initWithView:view renderer:self.renderer];
    if(!self.displayDriver)view.paused=NO;
    if (self.renderer->state->duration>0) [NSTimer scheduledTimerWithTimeInterval:self.renderer->state->duration repeats:NO block:^(NSTimer *timer){(void)timer;[NSApp terminate:nil];}];
}
- (void)synchronizeWindowDrawable {
    if([self.window.contentView isKindOfClass:MTKView.class])synchronizeGameDrawable((MTKView *)self.window.contentView);
}
- (void)windowDidResize:(NSNotification *)note {(void)note;[self synchronizeWindowDrawable];}
- (void)windowDidChangeScreen:(NSNotification *)note {(void)note;[self synchronizeWindowDrawable];}
- (void)windowDidEnterFullScreen:(NSNotification *)note {(void)note;[self synchronizeWindowDrawable];}
- (void)windowDidExitFullScreen:(NSNotification *)note {(void)note;[self synchronizeWindowDrawable];}
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)app {(void)app;return YES;}
- (void)windowDidBecomeKey:(NSNotification *)note {(void)note;[self.renderer setForeground:YES];self.renderer->state->inputFocused=true;[self.renderer publishInput];}
- (void)windowDidResignKey:(NSNotification *)note {(void)note;[self.renderer setForeground:NO];[self.renderer releaseInput];}
- (void)windowWillClose:(NSNotification *)note {(void)note;[self.renderer setForeground:NO];[self.renderer releaseInput];}
- (void)applicationDidBecomeActive:(NSNotification *)note {(void)note;if(self.window.keyWindow)[self.renderer setForeground:YES];}
- (void)applicationDidResignActive:(NSNotification *)note {(void)note;[self.renderer setForeground:NO];[self.renderer releaseInput];}
- (void)applicationWillTerminate:(NSNotification *)note {(void)note;if(@available(macOS 14.0,*))[(MetalDisplayDriver *)self.displayDriver stop];[self.renderer setForeground:NO];[self.renderer stopSession];[self.renderer writeReport];}
@end

static void savePNG(id<MTLTexture> texture,NSString *path) {
    NSUInteger width=texture.width,height=texture.height,row=width*4;std::vector<uint8_t> bytes(row*height);
    [texture getBytes:bytes.data() bytesPerRow:row fromRegion:MTLRegionMake2D(0,0,width,height) mipmapLevel:0];
    for (NSUInteger i=0;i<bytes.size();i+=4)std::swap(bytes[i],bytes[i+2]);
    NSBitmapImageRep *rep=[[NSBitmapImageRep alloc] initWithBitmapDataPlanes:nullptr pixelsWide:(NSInteger)width pixelsHigh:(NSInteger)height bitsPerSample:8 samplesPerPixel:4 hasAlpha:YES isPlanar:NO colorSpaceName:NSDeviceRGBColorSpace bytesPerRow:(NSInteger)row bitsPerPixel:32];
    memcpy(rep.bitmapData,bytes.data(),bytes.size());NSData *png=[rep representationUsingType:NSBitmapImageFileTypePNG properties:@{}];
    if (![png writeToFile:path atomically:YES])throw std::runtime_error("Cannot write rendered PNG");
}
static NSString *bundledSupportDirectory(NSString *resources) {
    NSString *support=NSProcessInfo.processInfo.environment[@"SCREAMER_SUPPORT_DIRECTORY"];
    if(support.length){
        if(!support.isAbsolutePath)throw std::runtime_error("Application support override must be absolute");
        return support;
    }
    // Product display names can change without moving existing saves or caches.
    NSString *name=applicationTitle(),*profile=[resources stringByAppendingPathComponent:@"SelectionConfig.json"];
    if([NSFileManager.defaultManager fileExistsAtPath:profile]){
        id stored=jsonFile(profile)[@"support_name"];
        if([stored isKindOfClass:NSString.class]&&[stored length]&&![stored containsString:@"/"]&&
           ![@[@".",@".."] containsObject:stored])name=stored;
    }
    if([name.pathComponents containsObject:@".."]||[name containsString:@"/"])throw std::runtime_error("Invalid application support directory name");
    return [[NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support"] stringByAppendingPathComponent:name];
}
static NSDictionary *prepareBundledSession(NSString *resources) {
    NSString *support=bundledSupportDirectory(resources);
    NSString *session=[[support stringByAppendingPathComponent:@"Sessions"] stringByAppendingPathComponent:NSUUID.UUID.UUIDString];
    NSError *error=nil;
    if(![NSFileManager.defaultManager createDirectoryAtPath:session withIntermediateDirectories:YES attributes:nil error:&error])throw std::runtime_error("Cannot create the game session folder");
    NSString *log=[session stringByAppendingPathComponent:@"session.log"];
    if(![NSFileManager.defaultManager createFileAtPath:log contents:NSData.data attributes:nil])throw std::runtime_error("Cannot create the session log");
    NSFileHandle *handle=[NSFileHandle fileHandleForWritingAtPath:log];if(!handle)throw std::runtime_error("Cannot open the session log");
    NSTask *task=[NSTask new];task.executableURL=[NSURL fileURLWithPath:[resources stringByAppendingPathComponent:@"Python/bin/python3.14"]];
    task.arguments=@[[resources stringByAppendingPathComponent:@"Live/Session.py"],@"--resources",resources,@"--session-dir",session,
        @"--data-dir",[support stringByAppendingPathComponent:@"GameData"],@"--parent-pid",[NSString stringWithFormat:@"%d",getpid()]];
    NSMutableDictionary *environment=[NSProcessInfo.processInfo.environment mutableCopy];
    [environment removeObjectForKey:@"PYTHONPATH"];[environment removeObjectForKey:@"__PYVENV_LAUNCHER__"];
    environment[@"PYTHONHOME"]=[resources stringByAppendingPathComponent:@"Python"];environment[@"PYTHONNOUSERSITE"]=@"1";
    environment[@"PYTHONDONTWRITEBYTECODE"]=@"1";environment[@"PYTHONUNBUFFERED"]=@"1";task.environment=environment;
    task.standardOutput=handle;task.standardError=handle;
    return @{@"task":task,@"log":handle,@"directory":session,@"state":[session stringByAppendingPathComponent:@"state.json"],@"input":[session stringByAppendingPathComponent:@"input.json"]};
}
int main(int argc,const char **argv) {
    @autoreleasepool {try {
        if(argc==2 && std::string(argv[1])=="--check-math") {checkProjectionMath();fprintf(stdout,"Projection reference checks passed\n");return 0;}
        NSString *scene=nil,*shader=nil,*replay=nil,*cars=nil,*live=nil,*input=nil,*report=nil,*offscreen=nil;bool noCars=false,liveSceneOnly=false,allowPartialHud=false,widescreen=true,extendedDistance=true;int render4K=-1;int width=3840,height=2160,frames=120;double duration=0,fixedTime=-1;
        for(int i=1;i<argc;i++){
            std::string a=argv[i];
            auto next=[&](){if(i+1>=argc)throw std::runtime_error("Missing command argument");return [NSString stringWithUTF8String:argv[++i]];};
            if(a=="--scene")scene=next();else if(a=="--shader")shader=next();else if(a=="--replay")replay=next();else if(a=="--cars")cars=next();else if(a=="--live")live=next();else if(a=="--input")input=next();else if(a=="--no-cars")noCars=true;else if(a=="--live-scene-only")liveSceneOnly=true;else if(a=="--render-4k")render4K=1;else if(a=="--window-resolution")render4K=0;else if(a=="--widescreen")widescreen=true;else if(a=="--original-aspect")widescreen=false;else if(a=="--extended-distance")extendedDistance=true;else if(a=="--standard-distance")extendedDistance=false;else if(a=="--allow-partial-hud")allowPartialHud=true;else if(a=="--report")report=next();else if(a=="--offscreen")offscreen=next();
            else if(a=="--width")width=std::stoi(next().UTF8String);else if(a=="--height")height=std::stoi(next().UTF8String);else if(a=="--frames")frames=std::stoi(next().UTF8String);else if(a=="--duration")duration=std::stod(next().UTF8String);else if(a=="--time")fixedTime=std::stod(next().UTF8String);else throw std::runtime_error("Unknown command argument");
        }
        NSString *resources=NSBundle.mainBundle.resourcePath;
        NSDictionary *session=nil;NSString *config=[resources stringByAppendingPathComponent:@"LiveConfig.json"];
        if(!live&&!offscreen&&[NSFileManager.defaultManager fileExistsAtPath:config]&&[jsonFile(config)[@"enabled"] boolValue]){
            session=prepareBundledSession(resources);live=session[@"state"];input=session[@"input"];
            if(!report)report=[session[@"directory"] stringByAppendingPathComponent:@"performance.json"];
        }
        if(!scene)scene=[resources stringByAppendingPathComponent:@"Scene/scene.json"];
        if(!shader)shader=[resources stringByAppendingPathComponent:@"World.metal"];
        NSString *bundledReplay=[resources stringByAppendingPathComponent:@"Replay/replay.json"];
        if(!replay && [NSFileManager.defaultManager fileExistsAtPath:bundledReplay])replay=bundledReplay;
        NSString *bundledCars=[resources stringByAppendingPathComponent:@"Cars/scene.json"];
        if(!cars && !noCars && [NSFileManager.defaultManager fileExistsAtPath:bundledCars])cars=bundledCars;
        if(noCars)cars=nil;
        if(live){replay=nil;if(!input)input=[live.stringByDeletingLastPathComponent stringByAppendingPathComponent:@"input.json"];}
        if(width<64||height<64||width>8192||height>8192||frames<1||frames>10000||!std::isfinite(duration)||duration<0||!std::isfinite(fixedTime)||fixedTime< -1)throw std::runtime_error("Invalid preview dimensions or duration");
        PreviewRenderer *renderer=[[PreviewRenderer alloc] initWithScene:scene shader:shader replay:replay cars:cars report:report];renderer->state->widescreen=widescreen;renderer->state->extendedDistance=extendedDistance;renderer->state->render4K=render4K>=0?render4K:([NSFileManager.defaultManager fileExistsAtPath:config]&&[jsonFile(config)[@"render_4k"] boolValue]);renderer->state->allowPartialHud=allowPartialHud||([NSFileManager.defaultManager fileExistsAtPath:config]&&[jsonFile(config)[@"allow_partial_hud"] boolValue]);renderer->state->duration=duration;renderer->state->fixedTime=fixedTime;
        if(live){renderer->state->liveSceneOnly=liveSceneOnly;[renderer startLive:live input:input];}
        if(session){
            renderer->state->bundledGameUI=true;
            renderer->state->sessionTask=session[@"task"];renderer->state->sessionLog=session[@"log"];renderer->state->sessionDirectory=session[@"directory"];
            __weak PreviewRenderer *weakRenderer=renderer;
            renderer->state->sessionTask.terminationHandler=^(NSTask *task){dispatch_async(dispatch_get_main_queue(),^{PreviewRenderer *r=weakRenderer;if(!r)return;
                [r releaseInput];if(task.terminationReason==NSTaskTerminationReasonExit&&task.terminationStatus==0)[NSApp terminate:nil];
                else r->state->startupError=[NSString stringWithFormat:@"%@ stopped unexpectedly. Please close this window and try again.",applicationTitle()];});};
            NSError *error=nil;if(![renderer->state->sessionTask launchAndReturnError:&error])renderer->state->startupError=[NSString stringWithFormat:@"Unable to start %@. The game runtime could not be launched.",applicationTitle()];
        }
        if(offscreen){
            renderer->state->displayScheduler=@"offscreen-unpaced";
            MTLTextureDescriptor *d=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:(NSUInteger)width height:(NSUInteger)height mipmapped:NO];d.storageMode=MTLStorageModeShared;d.usage=MTLTextureUsageRenderTarget;
            id<MTLTexture> target=[renderer->state->device newTextureWithDescriptor:d];
            if(live){
                double deadline=nowSeconds()+8;
                do{
                    [NSRunLoop.mainRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.01]];
                    id<MTLCommandBuffer> warm=[renderer encodeTo:target drawable:nil];[warm waitUntilCompleted];
                    if(warm.status==MTLCommandBufferStatusError)throw std::runtime_error(warm.error.localizedDescription.UTF8String);
                }while(!renderer->state->liveNative&&nowSeconds()<deadline);
                if(!renderer->state->liveNative)throw std::runtime_error("Live native scene was not ready for offscreen capture");
            }
            for(int f=0;f<frames;f++){id<MTLCommandBuffer> cb=[renderer encodeTo:target drawable:nil];[cb waitUntilCompleted];if(cb.status==MTLCommandBufferStatusError)throw std::runtime_error(cb.error.localizedDescription.UTF8String);}
            savePNG(target,offscreen);[renderer writeReport];return 0;
        }
        [NSApplication sharedApplication];NSApp.activationPolicy=NSApplicationActivationPolicyRegular;PreviewApp *app=[PreviewApp new];app.renderer=renderer;NSApp.delegate=app;[NSApp run];return 0;
    }catch(const std::exception &e){fprintf(stderr,"Metal preview: %s\n",e.what());return 1;}}
}
