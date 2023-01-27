# Reece Williams | https://reece.sh | Jan 2023
# ----------------------------------------------
# pip install Flask redis flask_caching requests websockets
# pip install --upgrade urllib3
# ----------------------------------------------

import asyncio
import json
import re

import requests
import websockets
from flask import Flask, jsonify, request
from flask_cors import CORS, cross_origin
from flask_sock import Sock
from flask_socketio import emit

import CONFIG
from CONFIG import REDIS_DB
from HELPERS import increment_call_value, replace_rpc_text

# === FLASK ===
rpc_app = Flask(__name__)
sock = Sock(rpc_app)
cors = CORS(rpc_app, resources={r"/*": {"origins": "*"}})

RPC_ROOT_HTML: str


@rpc_app.before_first_request
def before_first_request():
    global RPC_ROOT_HTML
    CONFIG.update_cache_times()
    RPC_ROOT_HTML = replace_rpc_text()


# === ROUTES ===
@rpc_app.route("/", methods=["GET"])
@cross_origin()
def root():
    # get the data between :// and the final /
    base = re.search(r"\/\/.*\/", request.base_url).group(0)
    # remove any /'s
    base = base.replace("/", "")

    # </a><br><br>Endpoints that require arguments:<br><a href="//rpc.juno.website.xyz = rpc.juno.website.xyz
    rpc_url = re.search(
        r'(?<=:<br><a href="//)(.*?)(?=/abci_info\?">)', RPC_ROOT_HTML
    ).group(0)

    return RPC_ROOT_HTML.replace(rpc_url, base).replace("{BASE_URL}", base)


@rpc_app.route("/cache_info", methods=["GET"])
@cross_origin()
def cache_info():
    """
    Updates viewable cache times (seconds) at DOMAIN/cache_info.
    Auto updates for this program on update/change automatically without restart.

    We only store the data so any time its requested every X minutes, we regenerate the data.
    """
    key = f"{CONFIG.RPC_PREFIX};cache_times"
    v = REDIS_DB.get(key)
    if v:
        return jsonify(json.loads(v))

    CONFIG.update_cache_times()

    REDIS_DB.setex(key, 15 * 60, json.dumps(CONFIG.cache_times))
    return jsonify(CONFIG.cache_times)


@rpc_app.route("/<path:path>", methods=["GET"])
@cross_origin()
def get_rpc_endpoint(path):
    global total_calls

    url = f"{CONFIG.RPC_URL}/{path}"
    args = request.args

    key = f"{CONFIG.RPC_PREFIX};{url};{args}"

    cache_seconds = CONFIG.get_cache_time_seconds(path, is_rpc=True)
    if cache_seconds < 0:
        return jsonify(
            {
                "error": f"cosmos endpoint cache: The path '{path}' is disabled on this node..."
            }
        )

    v = REDIS_DB.get(key)
    if v:
        increment_call_value("total_cache;get_rpc_endpoint")
        return jsonify(json.loads(v))

    try:
        req = requests.get(url, params=args)
    except Exception as e:
        req = requests.get(f"{CONFIG.BACKUP_RPC_URL}/{path}", params=args)

    if req.status_code != 200:
        return jsonify(req.json())

    REDIS_DB.setex(key, cache_seconds, json.dumps(req.json()))
    increment_call_value("total_outbound;get_rpc_endpoint")

    return req.json()


@rpc_app.route("/", methods=["POST"])
@cross_origin()
def post_rpc_endpoint():
    REQ_DATA: dict = request.get_json()

    # if REQ_DATA is a list, its a batchhttp request from TendermintClient34.create client
    # TODO: cache this? or allow direct pass through?
    # Add duplicate post as well for backup like we do below
    if isinstance(REQ_DATA, list):
        req = requests.post(f"{CONFIG.RPC_URL}", json=REQ_DATA)
        return jsonify(req.json())

    method, params = REQ_DATA.get("method", None), REQ_DATA.get("params", None)
    key = f"{CONFIG.RPC_PREFIX};{method};{params}"

    cache_seconds = CONFIG.get_cache_time_seconds(method, is_rpc=True)
    if cache_seconds < 0:
        return jsonify(
            {
                "error": f"cosmos endpoint cache: The RPC method '{method}' is disabled on this node..."
            }
        )

    v = REDIS_DB.get(key)
    if v:
        increment_call_value("total_cache;post_endpoint")
        return jsonify(json.loads(v))

    try:
        req = requests.post(f"{CONFIG.RPC_URL}", data=json.dumps(REQ_DATA))
    except:
        req = requests.post(
            f"{CONFIG.BACKUP_RPC_URL}",
            data=json.dumps(REQ_DATA),
        )

    if req.status_code != 200:
        return jsonify(req.json())

    REDIS_DB.setex(key, cache_seconds, json.dumps(req.json()))
    increment_call_value("total_outbound;post_endpoint")

    return req.json()


# === socket bridge ===

# return JSONRPC/websockets
# JSONRPC requests can be also made via websocket. The websocket endpoint is at /websocket, e.g. localhost:26657/websocket. Asynchronous RPC functions like event subscribe and unsubscribe are only available via websockets.
# https://github.com/hashrocket/ws
# grpcurl -plaintext -d "{\"address\":\"juno10r39fueph9fq7a6lgswu4zdsg8t3gxlq670lt0\"}" wss://juno-rpc.reece.sh/websocket cosmos.bank.v1beta1.Query/AllBalances
# grpcurl -plaintext -d "{\"address\":\"juno10r39fueph9fq7a6lgswu4zdsg8t3gxlq670lt0\"}" 15.204.143.232:9090 cosmos.bank.v1beta1.Query/AllBalances
# curl -X GET -H "Content-Type: application/json" -H "x-cosmos-block-height: 6619410" http://15.204.143.232:1317/cosmos/bank/v1beta1/balances/juno10r39fueph9fq7a6lgswu4zdsg8t3gxlq670lt0


@sock.route("/websocket")
def websocket(ws):
    print("websocket connected")

    async def handle_subscribe():
        async with websockets.connect(CONFIG.RPC_WEBSOCKET) as websocket:
            while True:
                # receive data from the websocket
                data = await websocket.recv()
                if data == "close" or data == None:
                    emit("close", data)
                    await websocket.close()
                    break
                emit("message", data)

    asyncio.run(handle_subscribe())


if __name__ == "__main__":
    before_first_request()
    rpc_app.run(debug=True, host="0.0.0.0", port=CONFIG.RPC_PORT)
