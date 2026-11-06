# SPDX-License-Identifier: MIT
{ lib }:
{
  src,
  lockFile ? src + "/ant-purifier.lock.json",
  ...
}@args:
let
  data =
    if builtins.pathExists lockFile then
      builtins.addErrorContext "ant-purifier: cannot parse companion lock; run ant-purifier lock" (
        builtins.fromJSON (builtins.readFile lockFile)
      )
    else
      { };
in
if builtins.isAttrs data && (data.version or null) == 2 then
  (import ./legacy-basic/read-lock.nix { inherit lib; }) args
else
  (import ./read-lock.nix { inherit lib; }) args
