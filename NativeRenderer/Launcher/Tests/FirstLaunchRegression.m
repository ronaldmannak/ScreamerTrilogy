#define main launcherEntry
#ifndef LAUNCHER_SOURCE_FILE
#error Define LAUNCHER_SOURCE_FILE as the production Launcher.m path
#endif
#import LAUNCHER_SOURCE_FILE
#undef main

static int fail(int code,NSString *message){fprintf(stderr,"First launch regression: %s\n",message.UTF8String);return code;}
static BOOL fits(NSTextField *field){
    NSAttributedString *text=[[NSAttributedString alloc] initWithString:field.stringValue attributes:@{NSFontAttributeName:field.font}];
    NSRect bounds=[text boundingRectWithSize:NSMakeSize(field.frame.size.width,CGFLOAT_MAX) options:NSStringDrawingUsesLineFragmentOrigin|NSStringDrawingUsesFontLeading];
    return ceil(bounds.size.height)<=field.frame.size.height+1;
}
int main(int argc,const char **argv){@autoreleasepool{
    if(argc!=4)return fail(1,@"Expected resources, isolated content and preview paths");
    [NSApplication sharedApplication];NSApp.activationPolicy=NSApplicationActivationPolicyRegular;
    NSString *resources=[NSString stringWithUTF8String:argv[1]],*content=[NSString stringWithUTF8String:argv[2]];
    FirstLaunchImport *setup=[FirstLaunchImport new];setup.resources=resources;setup.content=content;
    setup.profile=readJSON([resources stringByAppendingPathComponent:@"SelectionConfig.json"]);
    [setup applicationDidFinishLaunching:[NSNotification notificationWithName:NSApplicationDidFinishLaunchingNotification object:NSApp]];
    if(!setup.choose.enabled||setup.completed||setup.cancelled)return fail(2,@"Import should wait for a source selection");
    for(NSView *view in setup.window.contentView.subviews){
        if(!NSContainsRect(setup.window.contentView.bounds,view.frame))return fail(3,@"Import control extends outside the view");
        if([view isKindOfClass:NSTextField.class]&&!fits((NSTextField *)view))return fail(4,@"Import copy does not fit");
    }
    [setup.window displayIfNeeded];NSView *view=setup.window.contentView;
    NSBitmapImageRep *rep=[view bitmapImageRepForCachingDisplayInRect:view.bounds];[view cacheDisplayInRect:view.bounds toBitmapImageRep:rep];
    if(![[rep representationUsingType:NSBitmapImageFileTypePNG properties:@{}] writeToFile:[NSString stringWithUTF8String:argv[3]] atomically:YES])return fail(5,@"Cannot save setup preview");
    [setup cancel:nil];
    if(setup.completed||!setup.cancelled||[NSFileManager.defaultManager fileExistsAtPath:content])return fail(6,@"Cancel must leave game data untouched");
    // Use an inert child to prove Cancel also stops an active NSTask. The backend
    // suite separately covers cancellation cleanup of its staged import files.
    NSTask *child=[NSTask new];child.executableURL=[NSURL fileURLWithPath:@"/bin/sleep"];child.arguments=@[@"30"];
    NSError *error=nil;if(![child launchAndReturnError:&error])return fail(7,error.localizedDescription);
    setup.task=child;setup.cancelled=NO;[setup cancel:nil];
    if(child.running||!setup.cancelled||setup.completed||child.terminationReason!=NSTaskTerminationReasonUncaughtSignal)return fail(8,@"Cancel must stop its active import task before the helper exits");
    [setup.window orderOut:nil];
    printf("First launch import view and cancellation passed\n");return 0;
}}
