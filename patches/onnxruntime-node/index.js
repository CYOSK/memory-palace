// onnxruntime-node 兼容层：转发到 onnxruntime-web (wasm)
import * as ns from "onnxruntime-web";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ort = ns.default ?? ns;
const here = dirname(fileURLToPath(import.meta.url));
ort.env.wasm.wasmPaths = join(here, "..", "onnxruntime-web", "dist") + "/";
ort.env.wasm.numThreads = 1;

const _create = ort.InferenceSession.create.bind(ort.InferenceSession);
ort.InferenceSession.create = (p, o = {}) => _create(p, { ...o, executionProviders: ["wasm"] });
export default ort;
