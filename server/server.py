"""RouteGuide gRPC server — demo for the Drift gRPC plugin."""

import json
import logging
import math
import os
import sys
import time
from concurrent import futures

import grpc
import routeguide_pb2
import routeguide_pb2_grpc

_DB_PATH = os.path.join(os.path.dirname(__file__), "route_guide_db.json")
_PORT = int(os.environ.get("PORT", "50051"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("routeguide.server")


def _calc_distance(start, end):
    coord_factor = 10_000_000.0
    lat_1 = start.latitude / coord_factor
    lat_2 = end.latitude / coord_factor
    lon_1 = start.longitude / coord_factor
    lon_2 = end.longitude / coord_factor

    radians = math.pi / 180.0
    lat_1_rad = lat_1 * radians
    lat_2_rad = lat_2 * radians
    delta_lat_rad = (lat_2 - lat_1) * radians
    delta_lon_rad = (lon_2 - lon_1) * radians

    a = (
        math.sin(delta_lat_rad / 2) ** 2
        + math.cos(lat_1_rad)
        * math.cos(lat_2_rad)
        * math.sin(delta_lon_rad / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return int(6371000 * c)


def _load_db():
    with open(_DB_PATH) as f:
        data = json.load(f)
    features = []
    for item in data:
        loc = item["location"]
        point = routeguide_pb2.Point(
            latitude=loc["latitude"], longitude=loc["longitude"]
        )
        features.append(routeguide_pb2.Feature(name=item["name"], location=point))
    return features


class RouteGuideServicer(routeguide_pb2_grpc.RouteGuideServicer):
    """Implements the RouteGuide service."""

    def __init__(self):
        self.db = _load_db()

    @staticmethod
    def _in_rectangle(point, rect):
        left = min(rect.lo.longitude, rect.hi.longitude)
        right = max(rect.lo.longitude, rect.hi.longitude)
        bottom = min(rect.lo.latitude, rect.hi.latitude)
        top = max(rect.lo.latitude, rect.hi.latitude)
        return (
            left <= point.longitude <= right
            and bottom <= point.latitude <= top
        )

    # ── Unary RPC ─────────────────────────────────────────────────────────

    def GetFeature(self, request, context):
        """Return the feature at the given Point, or a nameless feature if none."""
        logger.info(
            "GetFeature request received lat=%s lon=%s",
            request.latitude,
            request.longitude,
        )
        for feature in self.db:
            if (
                feature.location.latitude == request.latitude
                and feature.location.longitude == request.longitude
            ):
                logger.info(
                    "GetFeature response sent found=true name=%s lat=%s lon=%s",
                    feature.name,
                    request.latitude,
                    request.longitude,
                )
                return feature
                
        # No feature found — return empty-name feature at the requested location
        response = routeguide_pb2.Feature(name="", location=request)
        logger.info(
            "GetFeature response sent found=false lat=%s lon=%s",
            request.latitude,
            request.longitude,
        )
        return response

    def GetFeatureStrict(self, request, context):
        """Return feature or gRPC NOT_FOUND when no feature exists at the point."""
        logger.info(
            "GetFeatureStrict request received lat=%s lon=%s",
            request.latitude,
            request.longitude,
        )
        for feature in self.db:
            if (
                feature.location.latitude == request.latitude
                and feature.location.longitude == request.longitude
            ):
                logger.info(
                    "GetFeatureStrict response sent found=true name=%s lat=%s lon=%s",
                    feature.name,
                    request.latitude,
                    request.longitude,
                )
                return feature

        logger.info(
            "GetFeatureStrict response sent status=NOT_FOUND lat=%s lon=%s",
            request.latitude,
            request.longitude,
        )
        context.abort(grpc.StatusCode.NOT_FOUND, "feature not found")

    def BatchLookup(self, request, context):
        """Return one Feature per requested Point (demonstrates repeated fields)."""
        logger.info(
            "BatchLookup request received locations_count=%s",
            len(request.locations),
        )
        results = []
        found_count = 0
        for point in request.locations:
            found = None
            for feature in self.db:
                if (
                    feature.location.latitude == point.latitude
                    and feature.location.longitude == point.longitude
                ):
                    found = feature
                    break
            if found:
                results.append(found)
                found_count += 1
            else:
                results.append(routeguide_pb2.Feature(name="", location=point))
        response = routeguide_pb2.BatchLookupResponse(features=results)
        logger.info(
            "BatchLookup response sent features_count=%s found_count=%s missing_count=%s",
            len(results),
            found_count,
            len(results) - found_count,
        )
        return response

    def GetFeatureMetadata(self, request, context):
        """Return metadata key/value pairs for a feature (demonstrates map fields)."""
        logger.info(
            "GetFeatureMetadata request received lat=%s lon=%s",
            request.latitude,
            request.longitude,
        )
        for feature in self.db:
            if (
                feature.location.latitude == request.latitude
                and feature.location.longitude == request.longitude
            ):
                response = routeguide_pb2.FeatureMetadata(
                    name=feature.name,
                    location=feature.location,
                    properties={"category": "landmark", "source": "routeguide-db"},
                    source_id="db-entry",
                )
                logger.info(
                    "GetFeatureMetadata response sent found=true name=%s",
                    feature.name,
                )
                return response
        response = routeguide_pb2.FeatureMetadata(
            name="",
            location=request,
            properties={},
            source_rank=0,
        )
        logger.info("GetFeatureMetadata response sent found=false")
        return response

    def GetRatedFeature(self, request, context):
        """Return a quality-rated feature. Known features are rated HIGH; unknown locations UNSPECIFIED."""
        logger.info(
            "GetRatedFeature request received lat=%s lon=%s",
            request.latitude,
            request.longitude,
        )
        for feature in self.db:
            if (
                feature.location.latitude == request.latitude
                and feature.location.longitude == request.longitude
            ):
                response = routeguide_pb2.RatedFeature(
                    name=feature.name,
                    location=feature.location,
                    quality=routeguide_pb2.HIGH,
                )
                logger.info(
                    "GetRatedFeature response sent found=true name=%s quality=HIGH",
                    feature.name,
                )
                return response
        response = routeguide_pb2.RatedFeature(
            name="",
            location=request,
            quality=routeguide_pb2.FEATURE_QUALITY_UNSPECIFIED,
        )
        logger.info("GetRatedFeature response sent found=false quality=UNSPECIFIED")
        return response

    # ── Streaming RPCs ─────────────────────────────────────────────────────

    def ListFeatures(self, request, context):
        logger.info("ListFeatures request received")
        sent = 0
        for feature in self.db:
            if self._in_rectangle(feature.location, request):
                sent += 1
                logger.info(
                    "ListFeatures response item sent name=%s lat=%s lon=%s",
                    feature.name,
                    feature.location.latitude,
                    feature.location.longitude,
                )
                yield feature
        logger.info("ListFeatures response stream completed sent_count=%s", sent)

    def RecordRoute(self, request_iterator, context):
        logger.info("RecordRoute request stream started")
        start = time.time()
        point_count = 0
        feature_count = 0
        distance = 0
        prev = None

        for point in request_iterator:
            point_count += 1
            logger.info(
                "RecordRoute request item received point_index=%s lat=%s lon=%s",
                point_count,
                point.latitude,
                point.longitude,
            )

            for feature in self.db:
                if (
                    feature.location.latitude == point.latitude
                    and feature.location.longitude == point.longitude
                ):
                    feature_count += 1
                    break

            if prev is not None:
                distance += _calc_distance(prev, point)
            prev = point

        response = routeguide_pb2.RouteSummary(
            point_count=point_count,
            feature_count=feature_count,
            distance=distance,
            elapsed_time=int(time.time() - start),
        )
        logger.info(
            "RecordRoute response sent point_count=%s feature_count=%s distance=%s elapsed_time=%s",
            response.point_count,
            response.feature_count,
            response.distance,
            response.elapsed_time,
        )
        return response

    def RouteChat(self, request_iterator, context):
        logger.info("RouteChat request stream started")
        message_count = 0
        for note in request_iterator:
            message_count += 1
            logger.info(
                "RouteChat request item received index=%s lat=%s lon=%s message=%s",
                message_count,
                note.location.latitude,
                note.location.longitude,
                note.message,
            )
            response = routeguide_pb2.RouteNote(
                location=note.location,
                message=f"echo: {note.message}",
            )
            logger.info(
                "RouteChat response item sent index=%s lat=%s lon=%s message=%s",
                message_count,
                response.location.latitude,
                response.location.longitude,
                response.message,
            )
            yield response
        logger.info("RouteChat response stream completed sent_count=%s", message_count)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    routeguide_pb2_grpc.add_RouteGuideServicer_to_server(RouteGuideServicer(), server)
    server.add_insecure_port(f"[::]:{_PORT}")
    server.start()
    logger.info("RouteGuide server listening on port %s", _PORT)
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
