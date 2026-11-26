// SPDX-License-Identifier: GPL-3.0-only
// Exercise the actual asynchronous live asset switch using an immutable fixture.
// No game process, input API, game memory writes, or simulation is involved.
#ifndef PREVIEW_SOURCE_FILE
#error Define PREVIEW_SOURCE_FILE
#endif
#define main includedProductionMain
#include PREVIEW_SOURCE_FILE
#undef main

static void check(bool value,const char *message){if(!value)throw std::runtime_error(message);}
int main(int argc,const char **argv){@autoreleasepool{try{
    check(argc==4,"Usage: OriginalConditionsIntegration fixture.json World.metal output-directory");
    NSString *fixture=[NSString stringWithUTF8String:argv[1]],*shader=[NSString stringWithUTF8String:argv[2]],*output=[NSString stringWithUTF8String:argv[3]];
    check(![NSFileManager.defaultManager fileExistsAtPath:output],"Use a fresh output directory");
    [NSFileManager.defaultManager createDirectoryAtPath:output withIntermediateDirectories:YES attributes:nil error:nil];
    LiveFrame source=liveFrameFromJSON(jsonFile(fixture),fixture.stringByDeletingLastPathComponent);
    check(source.night.available&&source.hasCamera,"Fixture must contain original day/night assets and an immutable camera pose");
    PreviewRenderer *renderer=[[PreviewRenderer alloc] initWithScene:[NSString stringWithUTF8String:source.worldScene.c_str()] shader:shader replay:nil cars:[NSString stringWithUTF8String:source.carsScene.c_str()] report:nil];
    State &s=*renderer->state;s.livePath=fixture;s.liveSceneOnly=true;s.diagnosticCapture=true;
    s.framebufferTexture=s.whiteTexture;source.framePath=nil;source.frameSequence=0;
    s.framebufferSeq=0;source.hudComplete=true;source.diagnosticCapture=true;
    auto descriptor=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:1280 height:720 mipmapped:NO];
    descriptor.storageMode=MTLStorageModeShared;descriptor.usage=MTLTextureUsageRenderTarget;
    id<MTLTexture> target=[s.device newTextureWithDescriptor:descriptor];
    NSMutableArray *results=[NSMutableArray array];NSMutableArray<NSData *> *images=[NSMutableArray array];
    for(NSString *name in @[@"day",@"night",@"restored-day",@"fog"]){
        Conditions::Preset preset=[name isEqual:@"night"]?Conditions::Preset::Night:([name isEqual:@"fog"]?Conditions::Preset::Fog:Conditions::Preset::Day);
        s.conditionsTransition.setImmediate(preset);
        LiveFrame expected=frameWithOriginalNight(source,preset==Conditions::Preset::Night);
        bool ready=false;double deadline=nowSeconds()+30;
        do{
            source.sampleAt=source.publishedAt=nowSeconds();source.pose.t=source.sampleAt;source.seq++;
            {std::lock_guard<std::mutex> guard(s.liveLock);s.liveFrames={source};}
            [NSRunLoop.mainRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.01]];
            id<MTLCommandBuffer> command=[renderer encodeTo:target drawable:nil];[command waitUntilCompleted];
            check(command.status==MTLCommandBufferStatusCompleted,"Metal command failed during original asset switching");
            ready=s.liveNative&&[s.loadedWorldScene isEqual:[NSString stringWithUTF8String:expected.worldScene.c_str()]]&&[s.loadedCarsScene isEqual:[NSString stringWithUTF8String:expected.carsScene.c_str()]];
        }while(!ready&&nowSeconds()<deadline);
        check(ready,"Original day/night live asset switch failed to become ready");
        check(s.visibleCars==s.cars.size(),"Original night assets lost a captured car/part model identity");
        check(!s.inputPath&&!s.sessionTask&&s.inputSeq==0,"Visual asset selection touched game input or a game session");
        check(s.projection.width==source.projection.width&&s.projection.height==source.projection.height,"Asset switch changed original projection source");
        NSMutableData *pixels=[NSMutableData dataWithLength:1280*720*4];
        [target getBytes:pixels.mutableBytes bytesPerRow:1280*4 fromRegion:MTLRegionMake2D(0,0,1280,720) mipmapLevel:0];[images addObject:pixels];
        savePNG(target,[output stringByAppendingPathComponent:[name stringByAppendingString:@".png"]]);
        NSUInteger glows=0,modulated=0;for(const Batch &batch:s.batches){glows+=batch.blend;modulated+=batch.blendMode==BlendMode::Modulate2x;}
        [results addObject:@{@"preset":name,@"world_scene":s.loadedWorldScene,@"cars_scene":s.loadedCarsScene,@"triangles":@(s.triangles),@"textures":@(s.textures.count),@"visible_instances":@(s.visibleCars),@"glow_batches":@(glows),@"modulated_light_batches":@(modulated),@"sky_active":@(s.skyActive)}];
    }
    check([images[0] isEqual:images[2]],"Returning to Day did not restore the identical original rendered image");
    check(![images[0] isEqual:images[1]],"Original Night assets did not change the rendered image");
    check(s.gpuErrors==0,"GPU errors were recorded");
    NSDictionary *report=@{@"passed":@YES,@"modes":results,@"day_restored_identically":@YES,@"game_execution":@NO,@"input_or_memory_writes":@NO,@"render_width":@1280,@"render_height":@720};
    NSData *json=[NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:nil];
    check([json writeToFile:[output stringByAppendingPathComponent:@"report.json"] atomically:YES],"Cannot write original condition integration report");
    puts("Original day/night/fog asset switching and all captured model identities passed; no game execution or input.");return 0;
}catch(const std::exception &error){fprintf(stderr,"Original conditions integration: %s\n",error.what());return 1;}}}
