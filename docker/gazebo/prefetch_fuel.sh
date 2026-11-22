#!/usr/bin/env bash
set -e

install -d "$GZ_FUEL_CACHE_PATH"
while IFS='|' read -r owner model version; do
  case "$owner" in ''|\#*) continue ;; esac
  url="https://fuel.gazebosim.org/1.0/$owner/models/${model// /%20}/$version"
  gz fuel download -u "$url"
  test -f "$GZ_FUEL_CACHE_PATH/fuel.gazebosim.org/$owner/models/$model/$version/model.config"
done < "$1"
