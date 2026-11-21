# API error catalogue

Stable `code` values for RFC 9457 `application/problem+json` responses (docs/12 §1.1).
The problem `type` URL is `{api.error_type_base}#{slug}` where `slug` is the lower-case
code with underscores replaced by hyphens.

## validation-error

`VALIDATION_ERROR` (HTTP 422). Request body, query or path failed validation.

## not-found

`NOT_FOUND` (HTTP 404). The referenced resource does not exist.

## campaign-invalid-transition

`CAMPAIGN_INVALID_TRANSITION` (HTTP 409). Campaign lifecycle command is illegal for the
current status.

## space-invalid

`SPACE_INVALID` (HTTP 422). Scenario space definition is invalid.

## backend-unsupported-param

`BACKEND_UNSUPPORTED_PARAM` (HTTP 422). A parameter is not supported by the selected backend.

## no-workers

`NO_WORKERS` (HTTP 409). No worker is available for the campaign backend.

## precondition-failed

`PRECONDITION_FAILED` (HTTP 412). `If-Match` missing or stale on a mutating request.

## unauthorized

`UNAUTHORIZED` (HTTP 401). Bearer token missing or incorrect.

## internal

`INTERNAL` (HTTP 500). Unexpected server error; response includes `trace_id`, never a stack.
