#!/bin/sh
set -eu

envsubst '${VITE_AMAP_JS_API_KEY} ${VITE_AMAP_SECURITY_JS_CODE}' \
  < /usr/share/nginx/html/runtime-config.js.template \
  > /usr/share/nginx/html/runtime-config.js
