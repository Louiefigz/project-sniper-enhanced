/* Synthetic AVFrames only. No files, decoder, filters, tools, or qualification. */
#define _POSIX_C_SOURCE 200809L
#include "source_gamut_avframe.h"
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <libavutil/pixfmt.h>

static const uint32_t EDGE[16] = {
    0, 0x80000000, 1, 0x80000001, 0x007fffff, 0x807fffff, 0x3f800000,
    0x3f800001, 0x7f7fffff, 0xff7fffff, 0x7f800000, 0xff800000,
    0x7fc00000, 0xffc00000, 0x7f800001, 0x3f000000
};

static uint32_t bits_of(float value) {
    uint32_t bits;
    memcpy(&bits, &value, 4);
    return bits;
}

/* Refcounted buffers contain an unaligned prefix and conspicuous NaN padding. */
static AVFrame *test_frame(int width, int height, int negative) {
    AVFrame *frame = av_frame_alloc();
    assert(frame);
    frame->format = AV_PIX_FMT_GBRPF32LE;
    frame->width = width;
    frame->height = height;
    const int stride = width * 4 + 7;
    for (int plane = 0; plane < 3; plane++) {
        frame->buf[plane] = av_buffer_alloc((size_t)stride * height + 1);
        assert(frame->buf[plane]);
        memset(frame->buf[plane]->data, 0xff, frame->buf[plane]->size);
        frame->data[plane] = frame->buf[plane]->data + 1;
        frame->linesize[plane] = negative ? -stride : stride;
        if (negative) frame->data[plane] += (height - 1) * stride;
    }
    return frame;
}

static void put_sample(AVFrame *frame, int plane, int index, uint32_t bits) {
    uint8_t *row = frame->data[plane] + (ptrdiff_t)(index / frame->width) * frame->linesize[plane];
    memcpy(row + (index % frame->width) * 4, &bits, 4);
}

static void edge_frame(AVFrame *frame) {
    for (int index = 0; index < 16; index++) {
        put_sample(frame, 0, index, EDGE[index]);
        put_sample(frame, 1, index, index % 2 ? 0x80000000 : 0);
        put_sample(frame, 2, index, 0xbf000000);
    }
}

static void assert_edges(const SGGamutResult *result) {
    const SGGamutChannel *g = &result->channels[0], *b = &result->channels[1];
    const SGGamutChannel *r = &result->channels[2];
    assert(result->frame_count == 2 && result->pixel_count == 32 && result->payload_bytes == 384);
    assert(g->finite_count == 22 && g->nan_count == 6);
    assert(g->positive_infinity_count == 2 && g->negative_infinity_count == 2);
    assert(g->below_zero_count == 6 && g->above_one_count == 4);
    assert(bits_of(g->minimum) == 0xff7fffff && bits_of(g->maximum) == 0x7f7fffff);
    assert(b->finite_count == 32 && !b->below_zero_count && !b->above_one_count);
    assert(bits_of(b->minimum) == 0 && bits_of(b->maximum) == 0);
    assert(r->finite_count == 32 && r->below_zero_count == 32 && !r->above_one_count);
    assert(bits_of(r->minimum) == 0xbf000000 && bits_of(r->maximum) == 0xbf000000);
}

static SGGamutResult test_edges_and_strides(void) {
    SGGamutReducer *reducer = sg_gamut_create(4, 4, 2);
    SGGamutResult result;
    AVFrame *positive = test_frame(4, 4, 0), *negative = test_frame(4, 4, 1);
    edge_frame(positive);
    edge_frame(negative);
    assert(sg_gamut_add_frame(reducer, positive) == SG_GAMUT_OK);
    assert(sg_gamut_add_frame(reducer, negative) == SG_GAMUT_OK);
    assert(sg_gamut_finish(reducer, &result) == SG_GAMUT_OK);
    assert_edges(&result);
    assert(sg_gamut_finish(reducer, &result) == SG_GAMUT_CLOSED);
    sg_gamut_free(&reducer);
    assert(!reducer);
    av_frame_free(&positive);
    av_frame_free(&negative);
    return result;
}

static void damage_frame(AVFrame *frame, int variant) {
    if (variant == 0) frame->format = AV_PIX_FMT_GBRPF32BE;
    if (variant == 1) frame->width = 2;
    if (variant == 2) frame->height = INT_MAX;
    if (variant == 3) frame->linesize[2] = 15;
    if (variant == 4) frame->linesize[2] = INT_MIN;
    if (variant == 5) frame->data[2] = NULL;
    if (variant == 6) frame->buf[2]->size = 85;
    if (variant == 7) frame->data[2] = frame->buf[2]->data;
    if (variant == 8) frame->linesize[2] = 0;
}

/* Invalid final-plane/tail cases must not partially add the first two planes. */
static void rejection_case(int variant) {
    AVFrame *frame = test_frame(4, 4, variant == 7);
    edge_frame(frame);
    SGGamutReducer *reducer = sg_gamut_create(4, 4, 2);
    SGGamutResult before, after;
    assert(sg_gamut_add_frame(reducer, frame) == SG_GAMUT_OK);
    assert(sg_gamut_snapshot(reducer, &before) == SG_GAMUT_OK);
    damage_frame(frame, variant);
    assert(sg_gamut_add_frame(reducer, frame) == SG_GAMUT_INVALID);
    assert(sg_gamut_snapshot(reducer, &after) == SG_GAMUT_OK);
    assert(memcmp(&before, &after, sizeof(before)) == 0);
    assert(sg_gamut_finish(reducer, &after) == SG_GAMUT_CLOSED);
    assert(sg_gamut_add_frame(reducer, frame) == SG_GAMUT_CLOSED);
    sg_gamut_free(&reducer);
    av_frame_free(&frame);
}

static void test_bounds(void) {
    assert(!sg_gamut_create(0, 4, 1));
    assert(!sg_gamut_create(3, 4, 1));
    assert(!sg_gamut_create(3842, 2160, 1));
    assert(!sg_gamut_create(3840, 2162, 1));
    assert(!sg_gamut_create(4, 4, 0));
    assert(!sg_gamut_create(4, 4, UINT64_MAX));
    SGGamutReducer *maximum = sg_gamut_create(3840, 2160, 24000);
    assert(maximum);
    sg_gamut_free(&maximum);
    for (int variant = 0; variant < 9; variant++) rejection_case(variant);
}

static void test_counts_and_empty_finite(void) {
    AVFrame *frame = test_frame(2, 2, 0);
    SGGamutReducer *reducer = sg_gamut_create(2, 2, 1);
    SGGamutResult result, before, sentinel;
    memset(&sentinel, 0xa5, sizeof(sentinel));
    before = sentinel;
    assert(sg_gamut_finish(reducer, &sentinel) == SG_GAMUT_INCOMPLETE);
    assert(memcmp(&before, &sentinel, sizeof(before)) == 0);
    sg_gamut_free(&reducer);
    reducer = sg_gamut_create(2, 2, 1);
    assert(sg_gamut_add_frame(reducer, frame) == SG_GAMUT_OK);
    assert(sg_gamut_snapshot(reducer, &before) == SG_GAMUT_OK);
    assert(sg_gamut_add_frame(reducer, frame) == SG_GAMUT_INVALID);
    assert(sg_gamut_snapshot(reducer, &result) == SG_GAMUT_OK);
    assert(memcmp(&before, &result, sizeof(before)) == 0);
    assert(result.channels[0].nan_count == 4 && result.channels[0].finite_count == 0);
    assert(bits_of(result.channels[0].minimum) == 0 && bits_of(result.channels[0].maximum) == 0);
    sg_gamut_free(&reducer);
    av_frame_free(&frame);
}

static double now_seconds(void) {
    struct timespec value;
    assert(clock_gettime(CLOCK_MONOTONIC, &value) == 0);
    return (double)value.tv_sec + value.tv_nsec / 1e9;
}

static void fill_benchmark_frame(AVFrame *frame) {
    for (int plane = 0; plane < 3; plane++) {
        for (int index = 0; index < frame->width * frame->height; index++)
            put_sample(frame, plane, index, 0x3f000000);
    }
}

/* Exact bits make finite extrema comparison independent of decimal spelling. */
static void print_parity(const SGGamutResult *result) {
    printf("{\"status\":\"complete\",\"syntheticCorrectnessPassed\":true,"
           "\"nativeMediaExecuted\":false,\"channels\":[");
    for (int plane = 0; plane < 3; plane++) {
        const SGGamutChannel *row = &result->channels[plane];
        if (plane) putchar(',');
        printf("{\"finiteCount\":%llu,\"nanCount\":%llu,\"positiveInfinityCount\":%llu,"
               "\"negativeInfinityCount\":%llu,\"belowZeroCount\":%llu,\"aboveOneCount\":%llu,"
               "\"minimumBits\":%u,\"maximumBits\":%u}",
               (unsigned long long)row->finite_count, (unsigned long long)row->nan_count,
               (unsigned long long)row->positive_infinity_count,
               (unsigned long long)row->negative_infinity_count,
               (unsigned long long)row->below_zero_count, (unsigned long long)row->above_one_count,
               bits_of(row->minimum), bits_of(row->maximum));
    }
    puts("]}");
}

/* One hot synthetic frame, 384 MiB active payload; excludes hash and framing. */
static void benchmark_once(void) {
    const double setup = now_seconds();
    AVFrame *frame = test_frame(512, 512, 0);
    fill_benchmark_frame(frame);
    SGGamutReducer *reducer = sg_gamut_create(512, 512, 128);
    SGGamutResult result;
    const double began = now_seconds();
    for (int index = 0; index < 128; index++)
        assert(sg_gamut_add_frame(reducer, frame) == SG_GAMUT_OK);
    assert(sg_gamut_finish(reducer, &result) == SG_GAMUT_OK);
    const double elapsed = now_seconds() - began;
    assert(result.payload_bytes == UINT64_C(402653184));
    printf("{\"status\":\"complete\",\"scope\":\"synthetic-hot-AVFrame-kernel-only\","
           "\"setupSeconds\":%.9f,\"elapsedSeconds\":%.9f,\"payloadBytes\":%llu,"
           "\"bytesPerSecond\":%.3f,\"samplesPerSecond\":%.3f,"
           "\"hashAndFramingIncluded\":false,\"nativeMediaExecuted\":false,"
           "\"gamutQualified\":false,\"transformApplicable\":false,\"twoHourProof\":false}\n",
           began - setup, elapsed, (unsigned long long)result.payload_bytes,
           result.payload_bytes / elapsed, result.payload_bytes / 4.0 / elapsed);
    sg_gamut_free(&reducer);
    av_frame_free(&frame);
}

int main(int argc, char **argv) {
    SGGamutResult result = test_edges_and_strides();
    test_bounds();
    test_counts_and_empty_finite();
    print_parity(&result);
    if (argc == 2 && strcmp(argv[1], "--benchmark") == 0) benchmark_once();
    return 0;
}
