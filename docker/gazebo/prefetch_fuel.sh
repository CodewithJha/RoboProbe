#!/usr/bin/env bash
set -e

cache=${GZ_FUEL_CACHE_PATH:?}
staging=
cleanup() {
  if [[ -n "$staging" ]]; then
    rm -rf -- "$staging"
    staging=
  fi
}
trap cleanup EXIT

mkdir -p "$cache"
while IFS='|' read -r owner model version; do
  case "$owner" in ''|\#*) continue ;; esac
  model_path="fuel.gazebosim.org/$owner/models/$model/$version"
  destination="$cache/$model_path"
  if [[ -f "$destination/model.config" ]]; then
    continue
  fi
  printf 'Caching %s/%s version %s\n' "$owner" "$model" "$version"
  url="https://fuel.gazebosim.org/1.0/$owner/models/$model/$version"
  for attempt in 1 2 3; do
    staging=$(mktemp -d "$cache/.fuel-download.XXXXXX")
    if GZ_FUEL_CACHE_PATH="$staging" gz fuel download -u "$url" </dev/null \
      && [[ -f "$staging/$model_path/model.config" ]]; then
      mkdir -p "$(dirname "$destination")"
      mv -nT -- "$staging/$model_path" "$destination"
      cleanup
      break
    fi
    cleanup
    sleep "$attempt"
  done
  if [[ ! -f "$destination/model.config" ]]; then
    printf 'Failed to cache %s/%s version %s\n' "$owner" "$model" "$version" >&2
    exit 1
  fi
done < "$1"
