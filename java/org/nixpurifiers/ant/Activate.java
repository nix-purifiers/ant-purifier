// SPDX-License-Identifier: MIT
package org.nixpurifiers.ant;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import org.apache.tools.ant.*;

/** Optional native Ant task; the Nix wrapper activates before all targets. */
public final class Activate extends Task {
    private String command() throws IOException, InterruptedException {
        String configured = System.getenv("ANT_PURIFIER_COMMAND");
        if (configured != null) return configured;
        Properties release = new Properties();
        try (InputStream resource = Activate.class.getResourceAsStream("release.properties")) {
            if (resource == null) return "ant-purifier";
            release.load(resource);
        }
        String reference = release.getProperty("reference");
        if (reference == null || !reference.startsWith("github:")) throw new IOException("Invalid plugin runtime reference");
        Path state = getProject().getBaseDir().toPath().resolve(".ant-purifier/native-runtime.properties");
        Properties cached = new Properties();
        if (Files.isRegularFile(state)) try (InputStream input = Files.newInputStream(state)) { cached.load(input); }
        if (reference.equals(cached.getProperty("reference")) && System.getProperty("os.arch").equals(cached.getProperty("architecture"))) {
            String path = cached.getProperty("command");
            if (path != null && path.startsWith("/nix/store/") && Files.isExecutable(Path.of(path))) return path;
        }
        Process build = new ProcessBuilder("nix", "build", "--no-link", "--print-out-paths", reference + "#cli")
            .redirectError(ProcessBuilder.Redirect.INHERIT).start();
        String output = new String(build.getInputStream().readAllBytes(), StandardCharsets.UTF_8).strip();
        if (build.waitFor() != 0) throw new IOException("Cannot build the released Ant plugin runtime");
        Path command = Path.of(output).resolve("bin/ant-purifier");
        if (!command.isAbsolute() || !Files.isExecutable(command)) throw new IOException("Invalid released Ant plugin runtime");
        Files.createDirectories(state.getParent());
        cached.setProperty("reference", reference); cached.setProperty("architecture", System.getProperty("os.arch"));
        cached.setProperty("command", command.toString());
        try (OutputStream target = Files.newOutputStream(state)) { cached.store(target, "Native Ant plugin runtime"); }
        return command.toString();
    }
    @Override public void execute() {
        if ("1".equals(System.getenv("ANT_PURIFIER_LOCKING"))) return;
        if (getProject().getReference("nix-purifier.active") != null) return;
        if (!"1".equals(System.getenv("ANT_PURIFIER_NIX_DELIVERED")))
            log("ant-purifier was resolved impurely; use the Ant wrapper for pure resolution of the plugin.", Project.MSG_WARN);
        String selected = System.getenv("ANT_PURIFIER_LOCKFILE");
        Path lock = selected == null ? getProject().getBaseDir().toPath().resolve("ant-purifier.lock.json") : Path.of(selected);
        if (!Files.exists(lock)) {
            log("No lockfile; using ordinary impure Ant/Ivy resolution.", Project.MSG_WARN);
            return;
        }
        try {
            String command = command();
            Process process = new ProcessBuilder(command, "--project", getProject().getBaseDir().toString(),
                                                 "prefetch", "--print-environment")
                .redirectError(ProcessBuilder.Redirect.INHERIT).start();
            String output = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8).strip();
            if (process.waitFor() != 0) throw new BuildException("ant-purifier prefetch failed");
            Path environment = Path.of(output);
            if (!environment.isAbsolute() || !Files.isRegularFile(environment.resolve("settings.xml")))
                throw new BuildException("ant-purifier returned an invalid environment");
            LockedListener listener = new LockedListener(environment, getProject().getBaseDir().toPath());
            getProject().addBuildListener(listener);
            getProject().addReference("nix-purifier.active", listener);
        } catch (IOException error) {
            throw new BuildException("Cannot activate ant-purifier; enter its nix shell first", error);
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt(); throw new BuildException("Activation interrupted", error);
        }
    }
}
