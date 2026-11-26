// SPDX-License-Identifier: GPL-3.0-only
// Visual conditions are frontend state; they never alter game clocks or input.
#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <string>
#include <simd/simd.h>

struct ConditionsUniforms {
    simd::float4 weights;  // night haze, original fog, reserved, Glide W scale
    simd::float4 fogColor;
    simd::float4 nightFog; // near distance, inverse span, reserved, reserved
    simd::float4 fogTable[16]; // Original 64-byte Glide table, normalized for Metal.
};
static_assert(sizeof(ConditionsUniforms)==304,"Conditions uniform layout must match Metal");

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
inline std::array<uint8_t,64> originalFogTable() {
    // Original 3dfx table generator (Rally 5527A / S2 56CA6), far=-25000.
    // The first 35 slots are zero; near is cached by the game but unused.
    std::array<uint8_t,64> table{};
    for(int index=3;index<32;index++){
        float depth=-800.f*(index-3),far=-25000.f;
        if(depth<far)depth=far-1;
        table[32+index]=static_cast<uint8_t>(255.0*std::sin(static_cast<double>(depth/far)*1.570796327));
    }
    return table;
}
inline ConditionsUniforms makeUniforms(simd::float2 blend,float /*referenceDistance*/,float nightNear=6000.f,float nightFar=35000.f,
        const std::array<uint8_t,64> &table=originalFogTable(),simd::float3 fogColor={184.f/255,184.f/255,184.f/255},float wScale=1.f) {
    for(int index=0;index<2;index++)blend[index]=std::isfinite(blend[index])?std::clamp(blend[index],0.f,1.f):0.f;
    float total=blend.x+blend.y;if(total>1)blend/=total;
    if(!std::isfinite(nightNear)||!std::isfinite(nightFar)||nightNear<0||nightFar<=nightNear){nightNear=6000;nightFar=35000;}
    if(!std::isfinite(wScale)||wScale<=0||wScale>1024)wScale=1;
    ConditionsUniforms result={(simd::float4){blend.x,blend.y,0,wScale},
            (simd::float4){fogColor.x,fogColor.y,fogColor.z,0},(simd::float4){nightNear,1.f/(nightFar-nightNear),0,0},{}};
    for(int index=0;index<64;index++)result.fogTable[index/4][index%4]=table[index]/255.f;
    return result;
}
} // namespace Conditions
