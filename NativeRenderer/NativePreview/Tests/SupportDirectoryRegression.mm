#ifndef PREVIEW_SOURCE_FILE
#error Define PREVIEW_SOURCE_FILE
#endif
#define main unusedPreviewMain
#include PREVIEW_SOURCE_FILE
#undef main
int main(){@autoreleasepool{
    NSString *temporary=[NSTemporaryDirectory() stringByAppendingPathComponent:[@"screamer-support-regression-" stringByAppendingString:NSUUID.UUID.UUIDString]];
    NSFileManager *fm=NSFileManager.defaultManager;NSError *error=nil;
    if(![fm createDirectoryAtPath:temporary withIntermediateDirectories:NO attributes:nil error:&error])return 1;
    unsetenv("SCREAMER_SUPPORT_DIRECTORY");
    NSString *profile=[temporary stringByAppendingPathComponent:@"SelectionConfig.json"];
    NSString *base=[NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support"];
    for(NSString *title in @[@"Screamer",@"Screamer 2",@"Screamer Rally"]){
        NSString *legacy=[title stringByAppendingString:@" Metal"];
        NSData *data=[NSJSONSerialization dataWithJSONObject:@{@"title":title,@"support_name":legacy} options:0 error:nil];
        if(![data writeToFile:profile atomically:YES])return 2;
        if(![bundledSupportDirectory(temporary) isEqual:[base stringByAppendingPathComponent:legacy]])return 3;
        NSString *isolated=[temporary stringByAppendingPathComponent:title];
        setenv("SCREAMER_SUPPORT_DIRECTORY",isolated.fileSystemRepresentation,1);
        if(![bundledSupportDirectory(temporary) isEqual:isolated])return 4;
        unsetenv("SCREAMER_SUPPORT_DIRECTORY");
    }
    NSData *invalid=[NSJSONSerialization dataWithJSONObject:@{@"support_name":@"../outside"} options:0 error:nil];
    if(![invalid writeToFile:profile atomically:YES])return 5;
    if(![bundledSupportDirectory(temporary) isEqual:[base stringByAppendingPathComponent:applicationTitle()]])return 6;
    [fm removeItemAtPath:profile error:nil];
    if(![bundledSupportDirectory(temporary) isEqual:[base stringByAppendingPathComponent:applicationTitle()]])return 7;
    setenv("SCREAMER_SUPPORT_DIRECTORY","relative",1);bool rejected=false;
    try{(void)bundledSupportDirectory(temporary);}catch(const std::exception &){rejected=true;}
    unsetenv("SCREAMER_SUPPORT_DIRECTORY");if(!rejected)return 8;
    if(![fm removeItemAtPath:temporary error:&error])return 9;
    puts("Three renamed games retain legacy support paths; explicit isolated roots win. No games or saves opened.");
    return 0;
}}
