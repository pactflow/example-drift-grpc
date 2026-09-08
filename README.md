# Example Drift gRPC Provider

[![Build](https://github.com/pactflow/example-drift-grpc/actions/workflows/build.yml/badge.svg)](https://github.com/pactflow/example-drift-grpc/actions/workflows/build.yml)

An example of using [Drift](https://support.smartbear.com/swagger/contract-testing/docs/en/drift.html) to verify that a
gRPC server actually does what its `.proto` file says it does — and to publish
that proof to [PactFlow](https://pactflow.io).

The service is the classic [RouteGuide](https://grpc.io/docs/languages/python/basics/)
example from the gRPC tutorial, implemented in Python.

## What problem does this solve?

A `.proto` file is a promise. It says `GetFeature` takes a `Point` and returns a
`Feature`, that `quality` is one of four enum values, that `RouteChat` streams in
both directions. But nothing stops the server from drifting away from that
promise — returning the wrong enum, dropping a field, or answering `OK` where it
should answer `NOT_FOUND`.

Drift closes that gap. You describe the behaviour you expect in YAML, Drift
drives real gRPC calls against your running server, and checks the responses
against the proto definition. The result is a verification bundle you publish to
PactFlow alongside the proto file, so consumers of your API can see not just what
you promised, but that you kept the promise.

## How it works

```
routeguide.proto ─────────────┐
  (the contract)              │
                              ├──> drift verify ──> verification results
server/server.py ─────────────┤                             │
  (the implementation)        │                             │
                              │                             v
drift/routeguide.testcases.yaml ─┘        PactFlow: proto contract + results
  (the expectations)
```

1. Drift loads `routeguide.proto` through its `grpc` plugin.
2. For each operation, it encodes `parameters.request.body` as the RPC's
   protobuf request message.
3. It sends the message over HTTP/2 to `/<package>.<Service>/<Method>`.
4. It decodes the response and asserts it matches `expected.response`.
5. CI publishes the proto file to PactFlow as a **gRPC provider contract**,
   with the verification results attached.

## Layout

```
├── routeguide.proto                  # The contract — source of truth
├── server/
│   ├── server.py                     # Python gRPC implementation
│   ├── route_guide_db.json           # Feature data
│   └── requirements.txt
├── drift/
│   ├── routeguide.testcases.yaml     # Drift test cases
│   └── routeguide.lua                # Lua helpers and lifecycle hooks
├── Makefile                          # All the commands below
└── .github/workflows/build.yml       # CI pipeline
```

The Python protobuf stubs (`server/routeguide_pb2*.py`) are generated from the
proto file by `make proto` and are deliberately not committed.

## Running it locally

### Prerequisites

- Python 3.9+
- [Drift](https://support.smartbear.com/swagger/contract-testing/docs/en/drift.html),
  with the `grpc` plugin installed
- A PactFlow account with Drift enabled, and `PACT_BROKER_BASE_URL` /
  `PACT_BROKER_TOKEN` set in your environment
- Docker (only for publishing to PactFlow)

### Verify the provider

```sh
make test
```

This creates a virtualenv, generates the gRPC stubs, starts the server, runs
`drift verify` against it, and shuts the server down. Results are written to
`output/`:

- `output/results/verification.*.result` — the bundle published to PactFlow,
  and uploaded as a CI artifact

To run the server on a different port (the default is `50051`):

```sh
make test PORT=50061
```

### Run the whole CI flow locally

```sh
make fake_ci
```

Verifies the provider and publishes the contract and results to PactFlow, using
a synthetic version number so you don't clash with real CI builds.

### Poke at the server by hand

```sh
make server
```

## Publishing to PactFlow

The proto file is published as the provider contract, with the Drift results
attached as evidence:

```sh
pactflow publish-provider-contract \
  routeguide.proto \
  --provider pactflow-example-drift-grpc \
  --provider-app-version "$(git rev-parse --short HEAD)" \
  --branch "$(git rev-parse --abbrev-ref HEAD)" \
  --specification grpc \
  --content-type text/plain \
  --verification-exit-code $EXIT_CODE \
  --verification-results output/results/verification.*.result \
  --verification-results-content-type application/vnd.smartbear.drift.result \
  --verifier drift
```

The contract is published whether verification passes or fails —
`--verification-exit-code` records which. A failing build still publishes, so
PactFlow shows the provider as unverified rather than silently showing stale
results.

> **Note:** PactFlow stores `grpc` provider contracts but does not compare them
> against consumer contracts, so this example does not use `can-i-deploy`. It is
> provider-side verification only. For the bi-directional flow with a consumer,
> see [example-bi-directional-provider-drift](https://github.com/pactflow/example-bi-directional-provider-drift).

## CI

[`.github/workflows/build.yml`](.github/workflows/build.yml) runs on every push
and pull request. It needs two settings on the repository:

| Setting | Type | Value |
|---|---|---|
| `PACT_BROKER_BASE_URL` | Variable (a secret also works) | Your PactFlow URL, e.g. `https://you.pactflow.io` |
| `PACT_BROKER_TOKEN` | Secret | A PactFlow API token with write access |

A variable is preferable for the URL — it isn't a credential, and leaving it
unmasked in the logs makes a misconfiguration obvious instead of showing `***`.

## What the test cases cover

Each operation in [`drift/routeguide.testcases.yaml`](drift/routeguide.testcases.yaml)
demonstrates a different part of the gRPC and protobuf surface.

| Test | RPC | Demonstrates |
|---|---|---|
| `GetFeature_KnownLocation` | `GetFeature` | Unary call, nested messages, a Lua matcher |
| `GetFeature_AnotherKnownLocation` | `GetFeature` | Partial response matching |
| `GetFeature_UnknownLocation` | `GetFeature` | Empty-string default values |
| `GetFeatureStrict_NotFound` | `GetFeatureStrict` | gRPC error status and message |
| `GetFeatureStrict_NotFound_MessageContains` | `GetFeatureStrict` | The `contains` matcher |
| `GetRatedFeature_KnownLocation` | `GetRatedFeature` | Enum fields, matched by name |
| `GetRatedFeature_UnknownLocation` | `GetRatedFeature` | Zero-value enums |
| `BatchLookup_TwoKnownLocations` | `BatchLookup` | Repeated fields, in and out |
| `BatchLookup_MixedLocations` | `BatchLookup` | Repeated fields with mixed results |
| `GetFeatureMetadata_KnownLocation` | `GetFeatureMetadata` | `map<string,string>` fields |
| `GetFeatureMetadata_OneofSourceId` | `GetFeatureMetadata` | `oneof` — the `source_id` branch |
| `GetFeatureMetadata_OneofSourceRank` | `GetFeatureMetadata` | `oneof` — the `source_rank` branch |
| `ListFeatures_SinglePointStream` | `ListFeatures` | Server-streaming responses |
| `RecordRoute_BasicClientStream` | `RecordRoute` | Client-streaming requests |
| `RouteChat_BidiEcho` | `RouteChat` | Bidirectional streaming |

### Writing a test case

A test case names the RPC to call, the request body to send, and the response to
expect:

```yaml
GetFeature_KnownLocation:
  target: routeguide:routeguide.RouteGuide/GetFeature
  parameters:
    request:
      body:
        latitude: 407838351
        longitude: -746143763
  expected:
    response:
      body:
        name: "Patriots Path, Mendham, NJ 07945, USA"
```

`target` is `<source name>:<package>.<Service>/<Method>`, where the source name
is defined in the `sources` block at the top of the file.

Response matching is partial — assert only the fields you care about. Streaming
RPCs use a YAML list for the request and/or response body, matched in order.

### Matching on more than exact values

`expected` values can be matchers rather than literals:

```yaml
grpc-message:
  contains: "not found"
```

Or Lua functions, defined in [`drift/routeguide.lua`](drift/routeguide.lua) and
referenced as `${functions:<name>}`:

```yaml
latitude: ${functions:required}   # assert present and non-zero
```

The same Lua file provides `operation:started` and `operation:finished` hooks,
which a real provider would use to seed and reset test state between calls.

## Trying it out

Break the contract and watch Drift catch it. Change `GetRatedFeature` in
`server/server.py` to return `MEDIUM` instead of `HIGH`, then run `make test`:

```
GetRatedFeature_KnownLocation FAILED
  expected quality to equal "HIGH" but was "MEDIUM"
```

## License

[MIT](LICENSE)
