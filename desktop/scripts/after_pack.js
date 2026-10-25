// electron-builder lässt node_modules in extraResources weg – der Next.js-Server braucht sie aber. Deshalb hier
// nach dem Packen (und vor dem Signieren) selbst in die App kopieren.
const { cpSync } = require("node:fs");
const { join } = require("node:path");

exports.default = async function afterPack(context) {
  const { appOutDir, electronPlatformName, packager } = context;
  const resources =
    electronPlatformName === "darwin"
      ? join(appOutDir, `${packager.appInfo.productFilename}.app`, "Contents", "Resources")
      : join(appOutDir, "resources");
  cpSync(join(__dirname, "..", "build", "web", "node_modules"), join(resources, "web", "node_modules"), {
    recursive: true,
    verbatimSymlinks: true,
  });
};
