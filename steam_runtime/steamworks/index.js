"use strict";

const nativeBinding = require("./dist/win64/steamworksjs.win32-x64-msvc.node");

let runCallbacksInterval;

module.exports.init = appId => {
  const { init, runCallbacks, ...api } = nativeBinding;
  init(appId);
  clearInterval(runCallbacksInterval);
  runCallbacksInterval = setInterval(runCallbacks, 1000 / 30);
  return api;
};
