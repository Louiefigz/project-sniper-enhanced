#ifndef SNIPER_SOURCE_GAMUT_AVFRAME_H
#define SNIPER_SOURCE_GAMUT_AVFRAME_H

/* Supplied AVFrame reduction only: no decode, PTS/EOF proof, hash, timer,
 * transform, source ownership, gamut qualification or approval. The caller
 * owns valid referenced AVFrames and must not mutate them concurrently.
 * Physical channel order is G, B, R; all active pixels, never row padding.
 */
#include <stdint.h>
#include <libavutil/frame.h>

enum SGGamutStatus {
    SG_GAMUT_OK = 0,
    SG_GAMUT_INVALID = -1,
    SG_GAMUT_INCOMPLETE = -2,
    SG_GAMUT_CLOSED = -3
};

typedef struct SGGamutChannel {
    uint64_t finite_count;
    uint64_t nan_count;
    uint64_t positive_infinity_count;
    uint64_t negative_infinity_count;
    uint64_t below_zero_count;
    uint64_t above_one_count;
    /* Meaningful only when finite_count != 0; zero extrema are positive. */
    float minimum;
    float maximum;
} SGGamutChannel;

typedef struct SGGamutResult {
    uint64_t frame_count;
    uint64_t pixel_count;
    uint64_t payload_bytes;
    SGGamutChannel channels[3];
} SGGamutResult;

typedef struct SGGamutReducer SGGamutReducer;

/* Bounds match existing V2 geometry/frame/pixel limits. No source is opened. */
SGGamutReducer *sg_gamut_create(unsigned width, unsigned height, uint64_t frames);
void sg_gamut_free(SGGamutReducer **reducer);

/* A rejected operation poisons the reducer, but leaves aggregate data intact. */
int sg_gamut_add_frame(SGGamutReducer *reducer, const AVFrame *frame);
int sg_gamut_finish(SGGamutReducer *reducer, SGGamutResult *result);

/* Partial diagnostics only, including after refusal; this is never proof. */
int sg_gamut_snapshot(const SGGamutReducer *reducer, SGGamutResult *result);

#endif
