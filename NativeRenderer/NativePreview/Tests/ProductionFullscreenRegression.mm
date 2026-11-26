#ifndef PREVIEW_SOURCE_FILE
#error Define PREVIEW_SOURCE_FILE as the absolute production NativePreview.mm path.
#endif
#define main frozen_production_main_unused
#include PREVIEW_SOURCE_FILE
#undef main
static FILE *integrationLog=nullptr;
static double integrationStarted=0;
static NSDictionary *integrationRect(NSRect r){return @{@"x":@(r.origin.x),@"y":@(r.origin.y),@"width":@(r.size.width),@"height":@(r.size.height)};}
static NSDictionary *integrationSize(CGSize s){return @{@"width":@(s.width),@"height":@(s.height)};}
@interface ProductionFullscreenProbe:PreviewApp
@property(nonatomic,assign)NSUInteger enterCount;
@property(nonatomic,assign)NSUInteger exitCount;
- (void)record:(NSString *)stage;
@end
@implementation ProductionFullscreenProbe
- (void)record:(NSString *)stage {
    MTKView *view=(MTKView *)self.window.contentView;CAMetalLayer *layer=(CAMetalLayer *)view.layer;
    NSTextField *status=(NSTextField *)[view viewWithTag:701];NSScreen *screen=self.window.screen;
    NSMutableArray *statusWidthConstraints=[NSMutableArray array];
    for(NSLayoutConstraint *constraint in [view.constraints arrayByAddingObjectsFromArray:status.constraints?:@[]]){
        if((constraint.firstItem==status&&constraint.firstAttribute==NSLayoutAttributeWidth)||(constraint.secondItem==status&&constraint.secondAttribute==NSLayoutAttributeWidth))
            [statusWidthConstraints addObject:@{@"active":@(constraint.active),@"relation":@(constraint.relation),@"multiplier":@(constraint.multiplier),@"constant":@(constraint.constant)}];
    }
    NSDictionary *value=@{@"stage":stage,@"seconds":@(CACurrentMediaTime()-integrationStarted),
      @"app_active":@(NSApp.isActive),@"window_key":@(self.window.isKeyWindow),@"window_visible":@(self.window.isVisible),@"window_occlusion_visible":@((self.window.occlusionState&NSWindowOcclusionStateVisible)!=0),@"actual_fullscreen_style":@((self.window.styleMask&NSWindowStyleMaskFullScreen)!=0),@"did_enter_count":@(self.enterCount),@"did_exit_count":@(self.exitCount),
      @"view_class":NSStringFromClass(view.class),@"display_driver_class":NSStringFromClass([self.displayDriver class]),
      @"window_frame":integrationRect(self.window.frame),@"window_content_layout_rect":integrationRect(self.window.contentLayoutRect),
      @"window_content_max_size":integrationSize(self.window.contentMaxSize),@"screen_frame":integrationRect(screen.frame),
      @"fullscreen_width_occupancy":@(screen.frame.size.width>0?view.frame.size.width/screen.frame.size.width:0),
      @"status_label_exists":@(status!=nil),@"status_label_hidden":@(status!=nil&&status.hidden),@"status_label_width_constraints":statusWidthConstraints,
      @"layer_contents_gravity":layer.contentsGravity?:@"",@"layer_contents_rect":integrationRect(NSRectFromCGRect(layer.contentsRect)),
      @"view_frame":integrationRect(view.frame),@"view_bounds":integrationRect(view.bounds),@"view_backing_rect":integrationRect([view convertRectToBacking:view.bounds]),
      @"view_drawable_size":integrationSize(view.drawableSize),@"layer_frame":integrationRect(layer.frame),@"layer_bounds":integrationRect(layer.bounds),@"layer_contents_scale":@(layer.contentsScale),@"layer_drawable_size":integrationSize(layer.drawableSize),
      @"metrics":[self.renderer metrics]};
    NSData *raw=[NSJSONSerialization dataWithJSONObject:value options:NSJSONWritingSortedKeys error:nil];if(raw){fwrite(raw.bytes,1,raw.length,integrationLog);fwrite("\n",1,1,integrationLog);fflush(integrationLog);}
}
- (void)applicationDidFinishLaunching:(NSNotification *)note {
    integrationStarted=CACurrentMediaTime();[super applicationDidFinishLaunching:note];[self record:@"windowed_initial"];
    // Exercise the real game-overlay UI branch while keeping all live services
    // disabled. A harmless 16:9 framebuffer lets the original status label hide.
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,500*NSEC_PER_MSEC),dispatch_get_main_queue(),^{
        MTLTextureDescriptor *d=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:16 height:9 mipmapped:NO];d.storageMode=MTLStorageModeShared;d.usage=MTLTextureUsageShaderRead;
        id<MTLTexture> placeholder=[self.renderer->state->device newTextureWithDescriptor:d];uint8_t pixels[16*9*4];for(size_t n=0;n<sizeof(pixels);n+=4){pixels[n]=192;pixels[n+1]=96;pixels[n+2]=32;pixels[n+3]=255;}
        [placeholder replaceRegion:MTLRegionMake2D(0,0,16,9) mipmapLevel:0 withBytes:pixels bytesPerRow:16*4];self.renderer->state->framebufferTexture=placeholder;
    });
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,1*NSEC_PER_SEC),dispatch_get_main_queue(),^{[self record:@"windowed_settled"];});
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,2*NSEC_PER_SEC),dispatch_get_main_queue(),^{[self record:@"before_toggle_enter"];[self.window toggleFullScreen:self];});
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC),dispatch_get_main_queue(),^{self.renderer->state->render4K=false;[self record:@"window_resolution_selected"];});
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,6*NSEC_PER_SEC),dispatch_get_main_queue(),^{[self record:@"fullscreen_window_resolution_checkpoint"];});
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,7*NSEC_PER_SEC),dispatch_get_main_queue(),^{self.renderer->state->render4K=true;[self record:@"4k_restored"];});
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,8*NSEC_PER_SEC),dispatch_get_main_queue(),^{[self record:@"before_toggle_exit"];if(self.window.styleMask&NSWindowStyleMaskFullScreen)[self.window toggleFullScreen:self];});
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,12*NSEC_PER_SEC),dispatch_get_main_queue(),^{[self record:@"windowed_after_exit_checkpoint"];});
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,14*NSEC_PER_SEC),dispatch_get_main_queue(),^{[self record:@"final"];[NSApp terminate:nil];});
}
- (void)windowDidEnterFullScreen:(NSNotification *)note {[super windowDidEnterFullScreen:note];self.enterCount++;[self record:@"did_enter_fullscreen"];dispatch_after(dispatch_time(DISPATCH_TIME_NOW,800*NSEC_PER_MSEC),dispatch_get_main_queue(),^{[self record:@"fullscreen_settled"];});}
- (void)windowDidExitFullScreen:(NSNotification *)note {[super windowDidExitFullScreen:note];self.exitCount++;[self record:@"did_exit_fullscreen"];dispatch_after(dispatch_time(DISPATCH_TIME_NOW,800*NSEC_PER_MSEC),dispatch_get_main_queue(),^{[self record:@"exit_settled"];});}
- (void)windowDidFailToEnterFullScreen:(NSWindow *)window {(void)window;[self record:@"failed_to_enter_fullscreen"];}
- (void)windowDidFailToExitFullScreen:(NSWindow *)window {(void)window;[self record:@"failed_to_exit_fullscreen"];}
- (void)applicationWillTerminate:(NSNotification *)note {[self record:@"terminated"];[super applicationWillTerminate:note];}
@end
int main(int argc,const char **argv){@autoreleasepool{try{
  NSString *scene=nil,*shader=nil,*cars=nil,*log=nil,*report=nil;bool widescreen=true;
  for(int i=1;i<argc;i++){
    std::string flag=argv[i];if(flag=="--original-aspect"){widescreen=false;continue;}if(i+1>=argc)throw std::runtime_error("Missing CLI value");
    NSString *value=[NSString stringWithUTF8String:argv[++i]];
    if(flag=="--scene")scene=value;else if(flag=="--shader")shader=value;
    else if(flag=="--cars")cars=value;else if(flag=="--log")log=value;
    else if(flag=="--report")report=value;else throw std::runtime_error("Unknown CLI option");
  }
  if(!scene||!shader||!log||!report)throw std::runtime_error("Required: --scene PATH --shader PATH --log PATH --report PATH; optional --cars PATH");
  integrationLog=fopen(log.fileSystemRepresentation,"w");if(!integrationLog)return 2;
  PreviewRenderer *renderer=[[PreviewRenderer alloc]initWithScene:scene shader:shader replay:nil cars:cars report:report];
  renderer->state->render4K=true;renderer->state->widescreen=widescreen;renderer->state->duration=0;
  // A sentinel path selects production game UI only. Do not call startLive:
  // no poller, Session, API, input path or game process is created.
  renderer->state->livePath=@"fullscreen-regression-no-live-service";renderer->state->inputPath=nil;
  [NSApplication sharedApplication];[NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];ProductionFullscreenProbe *delegate=[ProductionFullscreenProbe new];delegate.renderer=renderer;NSApp.delegate=delegate;[NSApp run];fclose(integrationLog);return 0;
}catch(const std::exception &e){fprintf(stderr,"%s\n",e.what());return 1;}}}
