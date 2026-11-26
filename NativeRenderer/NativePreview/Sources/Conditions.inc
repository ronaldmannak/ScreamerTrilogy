// SPDX-License-Identifier: GPL-3.0-only
// Visual conditions are frontend state; they never alter game clocks or input.
#include <algorithm>
#include <cctype>
#include <cmath>
#include <string>
#include <simd/simd.h>

struct ConditionsUniforms {
    simd::float4 weights;  // night haze, grey fog, fog start distance, inverse fog span
    simd::float4 fogColor;
    simd::float4 nightFog; // near distance, inverse span, reserved, reserved
};
static_assert(sizeof(ConditionsUniforms)==48,"Conditions uniform layout must match Metal");

namespace Conditions {
enum class Preset { Day, Night, Fog };
constexpr double transitionSeconds=.6;

inline const char *key(Preset preset) {
    switch(preset){case Preset::Night:return "night";case Preset::Fog:return "fog";default:return "day";}
}
inline bool fromString(const std::string &text,Preset &result) {
    std::string lower=text;
    for(char &value:lower)value=static_cast<char>(std::tolower(static_cast<unsigned char>(value)));
    if(lower=="day")result=Preset::Day;
    else if(lower=="night")result=Preset::Night;
    else if(lower=="fog")result=Preset::Fog;
    else return false;
    return true;
}
inline simd::float2 weights(Preset preset) {
    switch(preset){case Preset::Night:return {1,0};case Preset::Fog:return {0,1};default:return {0,0};}
}
struct Transition {
    Preset target=Preset::Day;
    simd::float2 previous={0,0};
    double started=0;

    simd::float2 sample(double now) const {
        simd::float2 destination=weights(target);
        if(!std::isfinite(now))return destination;
        double progress=std::clamp((now-started)/transitionSeconds,0.0,1.0);
        float blend=static_cast<float>(progress*progress*(3.0-2.0*progress));
        return previous+(destination-previous)*blend;
    }
    void select(Preset preset,double now) {
        if(preset!=Preset::Day&&preset!=Preset::Night&&preset!=Preset::Fog)preset=Preset::Day;
        if(preset==target)return;
        previous=sample(now);
        target=preset;
        started=std::isfinite(now)?now:0;
    }
    void setImmediate(Preset preset) {
        if(preset!=Preset::Day&&preset!=Preset::Night&&preset!=Preset::Fog)preset=Preset::Day;
        target=preset;previous=weights(preset);started=0;
    }
};
inline ConditionsUniforms makeUniforms(simd::float2 blend,float referenceDistance,float nightNear=6000.f,float nightFar=35000.f) {
    for(int index=0;index<2;index++)blend[index]=std::isfinite(blend[index])?std::clamp(blend[index],0.f,1.f):0.f;
    float total=blend.x+blend.y;if(total>1)blend/=total;
    float reference=std::isfinite(referenceDistance)&&referenceDistance>0?referenceDistance:32768.f;
    reference=std::clamp(reference,256.f,10000000.f);
    if(!std::isfinite(nightNear)||!std::isfinite(nightFar)||nightNear<0||nightFar<=nightNear){nightNear=6000;nightFar=35000;}
    return {(simd::float4){blend.x,blend.y,reference*.04f,1.f/(reference*.4f)},
            (simd::float4){.64f,.69f,.74f,0},(simd::float4){nightNear,1.f/(nightFar-nightNear),0,0}};
}
} // namespace Conditions
