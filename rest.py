# Reece Williams | https://reece.sh | Jan 2023

import json

import CONFIG as CONFIG
from CONFIG import REDIS_DB
from flask import Flask, jsonify, request
from flask_cors import CORS, cross_origin
from HELPERS import (
    Mode,
    download_openapi_locally,
    get_stats_html,
    get_swagger_code_from_source,
    increment_call_value,
    ttl_block_only,
)
from HELPERS_TYPES import CallType
from RequestsHandler import RestApiHandler

app = Flask(__name__)
cors = CORS(app, resources={r"/*": {"origins": "*"}})


REST_SWAGGER_HTML = ""
REST_HANDLER: RestApiHandler


@app.before_first_request
def before_first_request():
    global REST_HANDLER
    CONFIG.update_cache_times()
    download_openapi_locally()
    REST_HANDLER = RestApiHandler()

    # not used yet here
    # if len(CONFIG.RPC_WEBSOCKET) > 0:
    #     tmrpc = TendermintRPCWebSocket(enableSignal=False, logLevel=logging.DEBUG)
    #     t = threading.Thread(target=tmrpc.ws.run_forever)
    #     t.daemon = True
    #     t.start()


@app.route("/", methods=["GET"])
@cross_origin()
def root():
    global REST_SWAGGER_HTML

    if len(REST_SWAGGER_HTML) > 0:
        return REST_SWAGGER_HTML

    REST_SWAGGER_HTML = get_swagger_code_from_source()
    return REST_SWAGGER_HTML


@app.route("/<path:path>", methods=["GET"])
@cross_origin()
def get_rest(path):
    if path == "stats":
        # https://url/stats?password=123
        if (
            len(CONFIG.STATS_PASSWORD) > 0
            and request.args.get("password") != CONFIG.STATS_PASSWORD
        ):
            return "Invalid password"

        return get_stats_html()

    args = request.args

    cache_seconds = CONFIG.get_cache_time_seconds(path, is_rpc=False)
    if cache_seconds == Mode.DISABLED.value:
        return jsonify(
            {
                "error": f"cosmos endpoint cache: The path '{path}' is disabled on this node..."
            }
        )

    key = f"{CONFIG.REST_PREFIX};{ttl_block_only(cache_seconds)};{path};{args}"

    v = REDIS_DB.get(key)
    if v:
        increment_call_value(CallType.REST_GET_CACHE.value)
        return jsonify(json.loads(v))

    return jsonify(
        REST_HANDLER.handle_single_rest_get_requests(path, key, cache_seconds, args)
    )


@app.route("/<path:path>", methods=["POST"])
@cross_origin()
def post_rest(path):
    # REQ_DATA = json.loads(json.dumps(request.get_json(), separators=(",", ":")))
    # print(type(REQ_DATA))
    # return jsonify(REST_HANDLER.handle_single_rest_post_requests(path, REQ_DATA))
    return jsonify(
        {
            "error": f"cosmos endpoint cache: The path '{path}' does not yet have support on this REST API..."
        }
    )


if __name__ == "__main__":
    before_first_request()
    app.run(debug=True, host="0.0.0.0", port=CONFIG.REST_PORT)
