#define main launcherEntry
#ifndef LAUNCHER_SOURCE_FILE
#error Define LAUNCHER_SOURCE_FILE as the production Launcher.m path
#endif
#import LAUNCHER_SOURCE_FILE
#undef main

static int fail(int code,NSString *message){fprintf(stderr,"Selection regression: %s\n",message.UTF8String);return code;}
static BOOL contains(NSString *text,NSString *value){return [text rangeOfString:value options:NSCaseInsensitiveSearch].location!=NSNotFound;}
static BOOL fits(NSTextField *field){
    NSAttributedString *text=[[NSAttributedString alloc] initWithString:field.stringValue attributes:@{NSFontAttributeName:field.font}];
    NSRect bounds=[text boundingRectWithSize:NSMakeSize(field.frame.size.width,CGFLOAT_MAX) options:NSStringDrawingUsesLineFragmentOrigin|NSStringDrawingUsesFontLeading];
    return ceil(bounds.size.height)<=field.frame.size.height+1;
}
static BOOL saveView(NSView *view,NSString *path){
    [view.window displayIfNeeded];NSBitmapImageRep *rep=[view bitmapImageRepForCachingDisplayInRect:view.bounds];
    [view cacheDisplayInRect:view.bounds toBitmapImageRep:rep];
    return [[rep representationUsingType:NSBitmapImageFileTypePNG properties:@{}] writeToFile:path atomically:YES];
}

int main(int argc,const char **argv){@autoreleasepool{
    if(argc!=4)return fail(1,@"Expected resources, pending JSON, and preview PNG paths");
    NSDictionary *legacy=@{@"mode":@"classic",@"render_4k":@YES,@"widescreen":@NO,@"extended_distance":@NO,@"selection_accepted":@YES,@"unknown":@1};
    NSDictionary *normalized=options(legacy);
    if(normalized.count!=1||![normalized[@"mode"] isEqual:@"classic"])return fail(2,@"Old preferences must retain only mode");
    if(![options(@{}) isEqual:@{@"mode":@"upgraded"}]||![options(@{@"mode":@"invalid"}) isEqual:@{@"mode":@"upgraded"}])return fail(3,@"Default and invalid modes must use Upgraded");
    if(![options(@{@"mode":@"upgraded",@"render_4k":@NO,@"widescreen":@NO,@"extended_distance":@NO}) isEqual:@{@"mode":@"upgraded"}])return fail(4,@"Old graphics choices must not survive normalization");
    [NSApplication sharedApplication];NSApp.activationPolicy=NSApplicationActivationPolicyRegular;
    GameSelection *selection=[GameSelection new];selection.resources=[NSString stringWithUTF8String:argv[1]];selection.output=[NSString stringWithUTF8String:argv[2]];selection.settings=[normalized mutableCopy];
    NSData *pending=[NSJSONSerialization dataWithJSONObject:legacy options:NSJSONWritingPrettyPrinted error:nil];
    if(![pending writeToFile:selection.output atomically:YES])return fail(5,@"Cannot create isolated pending options");
    [selection applicationDidFinishLaunching:[NSNotification notificationWithName:NSApplicationDidFinishLaunchingNotification object:NSApp]];
    if(selection.mode.segmentCount!=2||![[selection.mode labelForSegment:0] isEqual:@"Classic"]||![[selection.mode labelForSegment:1] isEqual:@"Upgraded"]||selection.mode.selectedSegment!=0)return fail(6,@"Only Classic and Upgraded should be selectable, with saved mode preserved");
    NSUInteger buttons=0,selectors=0;
    for(NSView *view in selection.window.contentView.subviews){
        if([view isKindOfClass:NSPopUpButton.class])return fail(7,@"Graphics popups must be removed");
        if([view isKindOfClass:NSSegmentedControl.class])selectors++;
        if([view isKindOfClass:NSButton.class]){
            buttons++;NSString *title=[(NSButton *)view title];
            if(![@[@"Start game",@"Cancel"] containsObject:title])return fail(8,@"Only Start game and Cancel buttons should remain");
        }
        if(!NSContainsRect(selection.window.contentView.bounds,view.frame))return fail(9,@"A control extends outside the view");
    }
    if(buttons!=2||selectors!=1)return fail(10,@"Unexpected extra option controls");
    NSString *classicExplanation=selection.explanation.stringValue,*classicFeatures=selection.featureSummary.stringValue;
    if(!contains(classicExplanation,@"original")&&!contains(classicFeatures,@"original"))return fail(11,@"Classic should describe the original experience");
    if(!contains(classicExplanation,@"4:3")&&!contains(classicFeatures,@"4:3"))return fail(12,@"Classic should describe its original aspect ratio");
    if(!selection.featureSummary.cell.wraps||!fits(selection.featureSummary)||!fits(selection.explanation))return fail(13,@"Classic text must wrap and fit");
    NSString *preview=[NSString stringWithUTF8String:argv[3]],*classicPreview=[[preview stringByDeletingPathExtension] stringByAppendingString:@"-classic.png"];
    if(!saveView(selection.window.contentView,classicPreview))return fail(14,@"Cannot save Classic view preview");
    [selection cancel:nil];
    if(selection.accepted||![[NSData dataWithContentsOfFile:selection.output] isEqual:pending]||![selection.settings isEqual:normalized])return fail(15,@"Cancel must leave pending options and mode unchanged");
    if([selection applicationShouldTerminate:NSApp]!=NSTerminateCancel||selection.accepted||![[NSData dataWithContentsOfFile:selection.output] isEqual:pending])return fail(16,@"Quit must stop the helper without accepting or changing pending choices");
    [selection start:nil];NSDictionary *classicChosen=readJSON(selection.output);
    if(!selection.accepted||classicChosen.count!=2||![classicChosen[@"mode"] isEqual:@"classic"]||![classicChosen[@"selection_accepted"] boolValue]||![options(classicChosen) isEqual:@{@"mode":@"classic"}])return fail(22,@"Classic acceptance should preserve only its mode");
    selection.accepted=NO;
    selection.mode.selectedSegment=1;[selection modeChanged:nil];
    NSString *upgradedExplanation=selection.explanation.stringValue,*upgradedFeatures=selection.featureSummary.stringValue;
    if([classicExplanation isEqual:upgradedExplanation]||[classicFeatures isEqual:upgradedFeatures])return fail(17,@"Both mode descriptions should update");
    NSString *upgraded=[upgradedExplanation stringByAppendingFormat:@" %@",upgradedFeatures];
    if(!contains(upgraded,@"window")||!contains(upgraded,@"pixel")||!contains(upgraded,@"16:9")||(!contains(upgraded,@"full track")&&!contains(upgraded,@"full-track")))return fail(18,@"Upgraded copy must explain window pixels, widescreen, and full track");
    if(!selection.featureSummary.cell.wraps||!fits(selection.featureSummary)||!fits(selection.explanation))return fail(19,@"Upgraded text must wrap and fit");
    if(!saveView(selection.window.contentView,preview))return fail(20,@"Cannot save Upgraded view preview");
    [selection start:nil];NSDictionary *chosen=readJSON(selection.output);
    if(!selection.accepted||chosen.count!=2||![chosen[@"mode"] isEqual:@"upgraded"]||![chosen[@"selection_accepted"] boolValue]||![options(chosen) isEqual:@{@"mode":@"upgraded"}])return fail(21,@"Accepted output should persist only mode plus the temporary acceptance marker");
    [selection.window orderOut:nil];printf("Classic/Upgraded presets, wrapping copy, ignored legacy preferences and cancellation passed\n");return 0;
}}
