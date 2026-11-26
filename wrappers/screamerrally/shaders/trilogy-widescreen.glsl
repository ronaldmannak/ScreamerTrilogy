#version 330 core

// SPDX-FileCopyrightText:  2020-2026 The DOSBox Staging Team
// SPDX-FileCopyrightText:  2020-2020 Hyllian <sergiogdb@gmail.com>
// SPDX-FileCopyrightText:  2020-2020 jmarsh <jmarsh@vogons.org>
// SPDX-License-Identifier: GPL-2.0-or-later

// Adapted from DOSBox Staging 0.83.1 interpolation/sharp.glsl.
// Present a compressed 640x480 Hor+ game frame inside an exact 16:9 rectangle.
// Use with aspect=stretch, viewport=fit, and integer_scaling=off.
// This shader only presents the frame; the guest projection patch supplies the wider view.

/*

#pragma name        Main_Pass1
#pragma output_size Viewport

#pragma force_single_scan       on
#pragma force_no_pixel_doubling on

*/

#if defined(VERTEX)

layout(location = 0) in vec2 a_position;

out vec2 v_texCoord;
out vec2 prescale;

uniform vec2 INPUT_SIZE_0;
uniform vec2 OUTPUT_SIZE;

void main()
{
	gl_Position = vec4(a_position, 0.0, 1.0);

	const float targetAspect = 16.0 / 9.0;
	vec2 outputSize = max(OUTPUT_SIZE, vec2(1.0));
	float outputAspect = outputSize.x / outputSize.y;
	vec2 fitScale = vec2(1.0);
	if (outputAspect > targetAspect) {
		fitScale.x = targetAspect / outputAspect;
	} else {
		fitScale.y = outputAspect / targetAspect;
	}

	// Draw across the entire output so the fragment shader explicitly clears bars.
	// Mapping outside [0, INPUT_SIZE_0) identifies letterbox/pillarbox pixels.
	v_texCoord = (a_position / fitScale + vec2(1.0)) * 0.5 * INPUT_SIZE_0;
	prescale = max(ceil(outputSize * fitScale / INPUT_SIZE_0), vec2(1.0));
}

#elif defined(FRAGMENT)

in vec2 v_texCoord;
in vec2 prescale;

out vec4 FragColor;

uniform vec2 INPUT_SIZE_0;
uniform sampler2D INPUT_TEXTURE_0;

#define GAMMA             2.2
#define GAMMA_IN(color)   pow(color, vec4(GAMMA))
#define GAMMA_OUT(color)  pow(color, vec4(1.0 / GAMMA))

vec4 texture_linear(in sampler2D sampler, in vec2 uv)
{
	// subtract 0.5 here and add it again after the floor to centre the texel
	vec2 texCoord = uv * INPUT_SIZE_0 - vec2(0.5);

	vec2 s0t0 = floor(texCoord) + vec2(0.5);
	vec2 s0t1 = s0t0 + vec2(0.0, 1.0);
	vec2 s1t0 = s0t0 + vec2(1.0, 0.0);
	vec2 s1t1 = s0t0 + vec2(1.0);

	vec2 invTexSize = 1.0 / INPUT_SIZE_0;

	vec4 c_s0t0 = GAMMA_IN(texture(sampler, s0t0 * invTexSize));
	vec4 c_s0t1 = GAMMA_IN(texture(sampler, s0t1 * invTexSize));
	vec4 c_s1t0 = GAMMA_IN(texture(sampler, s1t0 * invTexSize));
	vec4 c_s1t1 = GAMMA_IN(texture(sampler, s1t1 * invTexSize));

	vec2 weight = fract(texCoord);

	vec4 c0 = c_s0t0 + (c_s1t0 - c_s0t0) * weight.x;
	vec4 c1 = c_s0t1 + (c_s1t1 - c_s0t1) * weight.x;

	return (c0 + (c1 - c0) * weight.y);
}

void main() {
	if (any(lessThan(v_texCoord, vec2(0.0))) ||
	    any(greaterThanEqual(v_texCoord, INPUT_SIZE_0))) {
		FragColor = vec4(0.0, 0.0, 0.0, 1.0);
		return;
	}

	const vec2 halfp   = vec2(0.5);
	vec2 texel_floored = floor(v_texCoord);
	vec2 s             = fract(v_texCoord);
	vec2 region_range  = halfp - halfp / prescale;

	vec2 center_dist = s - halfp;
	vec2 f = (center_dist - clamp(center_dist, -region_range, region_range)) *
	                 prescale + halfp;

	vec2 mod_texel = min(texel_floored + f, INPUT_SIZE_0 - halfp);

	FragColor = GAMMA_OUT(texture_linear(INPUT_TEXTURE_0, mod_texel / INPUT_SIZE_0));
}

#endif
