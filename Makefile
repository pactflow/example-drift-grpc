PACTICIPANT := pactflow-example-drift-grpc

# The proto file is both the source of truth for the tests and the provider
# contract that gets published to PactFlow.
PROTO_FILE := routeguide.proto

# Where the server listens, and the URL Drift verifies against.
PORT ?= 50051
SERVER_URL ?= grpc://localhost:$(PORT)

# Drift writes its results bundle and JUnit report under here.
OUTPUT_DIR := output
RESULTS_DIR := $(OUTPUT_DIR)/results
JUNIT_REPORT := $(OUTPUT_DIR)/reports/junit/verification-result.xml

VENV := .venv
PYTHON := $(VENV)/bin/python
STUBS := server/routeguide_pb2.py

# The Pact CLI is used only to publish the contract to PactFlow.
PACT_CLI := docker run --rm -v "$(PWD)":/app/tmp -e PACT_BROKER_BASE_URL -e PACT_BROKER_TOKEN pactfoundation/pact:latest
MOUNT := /app/tmp

GIT_COMMIT ?= $(shell git rev-parse --short HEAD)
GIT_BRANCH ?= $(shell git rev-parse --abbrev-ref HEAD)

.PHONY: all install proto server test ci fake_ci publish_provider_contract clean

all: test

## =====================
## Setup
## =====================

$(VENV)/bin/activate: server/requirements.txt
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --quiet --upgrade pip
	$(VENV)/bin/pip install --quiet -r server/requirements.txt
	touch $@

## Create the virtualenv and install the server's dependencies.
install: $(VENV)/bin/activate

$(STUBS): $(PROTO_FILE) $(VENV)/bin/activate
	$(PYTHON) -m grpc_tools.protoc -I. --python_out=server --grpc_python_out=server $(PROTO_FILE)

## Generate the Python protobuf/gRPC stubs from the proto file.
proto: $(STUBS)

## Run the gRPC server in the foreground (useful for poking at it by hand).
server: $(STUBS)
	PORT=$(PORT) $(PYTHON) server/server.py

## =====================
## Test
## =====================

## Start the server, verify it against the proto file with Drift, then stop it.
##
## Drift's exit code is the exit code of this target, so `ci` can report the
## verification outcome to PactFlow whether it passed or failed.
test: $(STUBS) clean
	@PORT=$(PORT) $(PYTHON) server/server.py & \
	SERVER_PID=$$!; \
	trap "kill $$SERVER_PID 2>/dev/null" EXIT; \
	for i in $$(seq 1 40); do \
	  nc -z localhost $(PORT) >/dev/null 2>&1 && break; \
	  sleep 0.25; \
	done; \
	drift verify \
	  --server-url $(SERVER_URL) \
	  --test-files drift/routeguide.testcases.yaml \
	  --output-dir $(OUTPUT_DIR) \
	  --generate-result

## =====================
## CI
## =====================

## Verify the provider, then publish the proto contract and the Drift results
## to PactFlow — whether verification passed or failed.
ci:
	@if $(MAKE) test; then \
		EXIT_CODE=0 $(MAKE) publish_provider_contract; \
	else \
		EXIT_CODE=1 $(MAKE) publish_provider_contract; \
	fi

## Run the CI flow locally, with CI-like environment variables.
fake_ci:
	CI=true \
	GIT_COMMIT=`git rev-parse --short HEAD`-`date +%s` \
	GIT_BRANCH=`git rev-parse --abbrev-ref HEAD` \
	$(MAKE) ci

## =====================
## PactFlow
## =====================

## Publish routeguide.proto to PactFlow as a gRPC provider contract, along with
## the Drift verification results that show the server conforms to it.
publish_provider_contract:
	@echo ""
	@echo "========== Publishing provider contract + verification results =========="
	@echo ""
	@RESULTS_FILE=$$(find $(RESULTS_DIR) -name 'verification.*.result' -type f | head -1); \
	if [ -z "$$RESULTS_FILE" ]; then \
	  echo "No Drift verification results found in $(RESULTS_DIR) — run 'make test' first"; \
	  exit 1; \
	fi; \
	$(PACT_CLI) pactflow publish-provider-contract \
	  $(MOUNT)/$(PROTO_FILE) \
	  --provider $(PACTICIPANT) \
	  --provider-app-version $(GIT_COMMIT) \
	  --branch $(GIT_BRANCH) \
	  --specification grpc \
	  --content-type text/plain \
	  --verification-exit-code=$${EXIT_CODE:-0} \
	  --verification-results "$(MOUNT)/$$RESULTS_FILE" \
	  --verification-results-content-type application/vnd.smartbear.drift.result \
	  --verifier drift \
	  --verifier-version "$$(drift --version)"

## =====================
## Misc
## =====================

clean:
	mkdir -p $(RESULTS_DIR) && rm -rf $(RESULTS_DIR)/*
