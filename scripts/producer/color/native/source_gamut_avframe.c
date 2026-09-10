/* In-process, constant-space IEEE754 sample reduction. Never media authority. */
#include "source_gamut_avframe.h"

#include <float.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <libavutil/pixfmt.h>

#if defined(__FAST_MATH__) || (defined(__FINITE_MATH_ONLY__) && __FINITE_MATH_ONLY__)
#error "Exact gamut classification forbids fast/finite-only math"
#endif
_Static_assert(sizeof(float) == 4 && FLT_RADIX == 2 && FLT_MANT_DIG == 24
               && FLT_MAX_EXP == 128, "IEEE754 binary32 required");

struct SGGamutReducer {
    unsigned width;
    unsigned height;
    uint64_t expected_frames;
    int closed;
    uint32_t minimum_key[3];
    uint32_t maximum_key[3];
    SGGamutResult result;
};

/* The input is specifically GBRPF32LE, not ambient-endian float data. */
static int little_endian(void) {
    const uint32_t word = 1;
    return *(const unsigned char *)&word == 1;
}

SGGamutReducer *sg_gamut_create(unsigned width, unsigned height, uint64_t frames) {
    const uint64_t pixel_limit = UINT64_C(199065600000);
    if (!little_endian() || width < 2 || height < 2 || width > 3840 || height > 2160
        || width % 2 || height % 2 || !frames || frames > 24000)
        return NULL;
    const uint64_t pixels = (uint64_t)width * height;
    if (frames > pixel_limit / pixels || frames > UINT64_MAX / pixels / 12)
        return NULL;
    SGGamutReducer *value = calloc(1, sizeof(*value));
    if (!value) return NULL;
    value->width = width;
    value->height = height;
    value->expected_frames = frames;
    return value;
}

void sg_gamut_free(SGGamutReducer **reducer) {
    if (!reducer) return;
    free(*reducer);
    *reducer = NULL;
}

/* Integer address arithmetic validates the complete referenced plane extent
 * before any pixel pointer arithmetic. Negative stride uses data as row zero.
 */
static int valid_plane(const AVFrame *frame, int plane) {
    const AVBufferRef *buffer = av_frame_get_plane_buffer(frame, plane);
    if (!buffer || !buffer->data || !frame->data[plane]) return 0;
    const uintptr_t base = (uintptr_t)buffer->data;
    const uintptr_t first = (uintptr_t)frame->data[plane];
    const uint64_t row_bytes = (uint64_t)frame->width * 4;
    const int64_t stride = frame->linesize[plane];
    const uint64_t step = (uint64_t)(stride < 0 ? -stride : stride);
    if (first < base || buffer->size > UINTPTR_MAX - base || step < row_bytes)
        return 0;
    const uint64_t offset = first - base;
    const uint64_t span = (uint64_t)(frame->height - 1) * step;
    if (offset > buffer->size) return 0;
    if (stride < 0)
        return span <= offset && row_bytes <= buffer->size - offset;
    return span <= buffer->size - offset
        && row_bytes <= buffer->size - offset - span;
}

/* All geometry/count and all planes must pass before aggregate mutation. */
static int valid_frame(const SGGamutReducer *reducer, const AVFrame *frame) {
    if (!frame || frame->format != AV_PIX_FMT_GBRPF32LE
        || frame->width != (int)reducer->width || frame->height != (int)reducer->height
        || reducer->result.frame_count >= reducer->expected_frames)
        return 0;
    for (int plane = 0; plane < 3; plane++) {
        if (!valid_plane(frame, plane)) return 0;
    }
    return 1;
}

/* Map finite bit patterns to numeric order, canonicalizing signed zero only. */
static uint32_t ordered_key(uint32_t bits) {
    return bits & UINT32_C(0x80000000) ? ~bits : bits ^ UINT32_C(0x80000000);
}

static void nonfinite_sample(SGGamutChannel *channel, uint32_t bits) {
    if (bits & UINT32_C(0x007fffff)) channel->nan_count++;
    else if (bits & UINT32_C(0x80000000)) channel->negative_infinity_count++;
    else channel->positive_infinity_count++;
}

/* Bit classification also preserves subnormals even if ambient FP mode flushes
 * arithmetic denormals. memcpy loads/stores permit unaligned input rows.
 */
static void add_sample(SGGamutReducer *reducer, int plane, uint32_t bits) {
    SGGamutChannel *channel = &reducer->result.channels[plane];
    if ((bits & UINT32_C(0x7f800000)) == UINT32_C(0x7f800000)) {
        nonfinite_sample(channel, bits);
        return;
    }
    const uint32_t magnitude = bits & UINT32_C(0x7fffffff);
    if ((bits & UINT32_C(0x80000000)) && magnitude) channel->below_zero_count++;
    if (!(bits & UINT32_C(0x80000000)) && bits > UINT32_C(0x3f800000))
        channel->above_one_count++;
    if (!magnitude) bits = 0;
    const uint32_t key = ordered_key(bits);
    if (!channel->finite_count || key < reducer->minimum_key[plane]) {
        reducer->minimum_key[plane] = key;
        memcpy(&channel->minimum, &bits, 4);
    }
    if (!channel->finite_count || key > reducer->maximum_key[plane]) {
        reducer->maximum_key[plane] = key;
        memcpy(&channel->maximum, &bits, 4);
    }
    channel->finite_count++;
}

static void reduce_row(SGGamutReducer *reducer, int plane, const uint8_t *row) {
    for (unsigned column = 0; column < reducer->width; column++) {
        uint32_t bits;
        memcpy(&bits, row + (size_t)column * 4, 4);
        add_sample(reducer, plane, bits);
    }
}

static void reduce_plane(SGGamutReducer *reducer, const AVFrame *frame, int plane) {
    for (unsigned row = 0; row < reducer->height; row++) {
        const ptrdiff_t offset = (ptrdiff_t)row * frame->linesize[plane];
        reduce_row(reducer, plane, frame->data[plane] + offset);
    }
}

int sg_gamut_add_frame(SGGamutReducer *reducer, const AVFrame *frame) {
    if (!reducer || reducer->closed) return SG_GAMUT_CLOSED;
    if (!valid_frame(reducer, frame)) {
        reducer->closed = 1;
        return SG_GAMUT_INVALID;
    }
    for (int plane = 0; plane < 3; plane++) reduce_plane(reducer, frame, plane);
    reducer->result.frame_count++;
    reducer->result.pixel_count += (uint64_t)reducer->width * reducer->height;
    reducer->result.payload_bytes += (uint64_t)reducer->width * reducer->height * 12;
    return SG_GAMUT_OK;
}

int sg_gamut_snapshot(const SGGamutReducer *reducer, SGGamutResult *result) {
    if (!reducer || !result) return SG_GAMUT_INVALID;
    *result = reducer->result;
    return SG_GAMUT_OK;
}

int sg_gamut_finish(SGGamutReducer *reducer, SGGamutResult *result) {
    if (!reducer || reducer->closed) return SG_GAMUT_CLOSED;
    reducer->closed = 1;
    if (!result) return SG_GAMUT_INVALID;
    if (reducer->result.frame_count != reducer->expected_frames)
        return SG_GAMUT_INCOMPLETE;
    *result = reducer->result;
    return SG_GAMUT_OK;
}
