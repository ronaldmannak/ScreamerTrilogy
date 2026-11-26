#define main bundledLauncherMain
#include "launcher.m"
#undef main

// Exercise failure atomicity without mutating an executable app bundle. macOS
// validates a bundle's resource seal before it reaches the launcher's checks.
int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 4) return 2;
        NSData *data = [NSData dataWithContentsOfFile:[NSString stringWithUTF8String:argv[1]]];
        NSDictionary *recipe = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        NSError *error = nil;
        NSString *result = prepareEnhancedProgram(recipe,
            [NSString stringWithUTF8String:argv[2]], [NSString stringWithUTF8String:argv[3]], YES, YES, &error);
        if (!result) {
            fprintf(stderr, "%s\n", error.localizedDescription.UTF8String);
            return 1;
        }
        return 0;
    }
}
