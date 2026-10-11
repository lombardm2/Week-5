#!/usr/bin/env bash
# Resolve the rollback target + reason for rollback-staging.yml.
#   push of tag rollback/<staging-tag>  -> target from tag name, reason from tag message
#   workflow_dispatch                   -> target and reason from inputs
# Inputs (env): EVENT, REF_NAME, IN_TAG, IN_REASON. Writes tag= and reason= to $GITHUB_OUTPUT.
set -euo pipefail
if [ "${EVENT}" = "push" ]; then
  TAG="${REF_NAME#rollback/}"
  # actions/checkout can replace annotated tags with lightweight ones; re-fetch to keep the message
  git fetch --force --quiet origin "refs/tags/${REF_NAME}:refs/tags/${REF_NAME}" || true
  REASON="$(git tag -l --format='%(contents:subject)' "${REF_NAME}")"
else
  TAG="${IN_TAG}"
  REASON="${IN_REASON}"
fi
if ! [[ "${TAG}" =~ ^staging-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{7}$ ]]; then
  echo "::error::not a staging release tag: '${TAG}'"; exit 1
fi
if ! git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null; then
  echo "::error::release tag not found: ${TAG} (available: $(git tag -l 'staging-*' | tr '\n' ' '))"; exit 1
fi
if [ -z "${REASON// /}" ]; then
  echo "::error::a reason is required (tag message, e.g. git tag -a ... -m \"INC-0042 ...\")"; exit 1
fi
echo "Rolling back staging to ${TAG}: ${REASON}"
{ echo "tag=${TAG}"; echo "reason=${REASON//$'\n'/ }"; } >> "${GITHUB_OUTPUT:-/dev/stdout}"
