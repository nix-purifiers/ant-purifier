// SPDX-License-Identifier: MIT
package org.nixpurifiers.ant;

import java.io.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import org.apache.tools.ant.*;
import org.apache.tools.ant.types.Reference;

/** Route native Ivy tasks to the Nix-resolved repository and native lock. */
public final class LockedListener implements BuildListener {
    private Path environment;
    private Path temporary;
    private Path projectRoot;
    private final Map<Project, Map<ClassLoader, Reference>> references = new IdentityHashMap<>();

    public LockedListener() {
        String root = System.getenv("ANT_PURIFIER_PROJECT_ROOT");
        if (root != null) projectRoot = Path.of(root).toAbsolutePath().normalize();
        String value = System.getenv("ANT_PURIFIER_ENVIRONMENT");
        if (value != null) activate(Path.of(value));
    }
    public LockedListener(Path environment, Path root) { projectRoot = root.toAbsolutePath().normalize(); activate(environment); }
    private void activate(Path value) {
        try {
            environment = value;
            String tempDir = System.getenv("TMPDIR");
            temporary = tempDir == null ? Files.createTempDirectory("ant-purifier-ivy-")
                : Files.createTempDirectory(Path.of(tempDir), "ant-purifier-ivy-");
            String settings = Files.readString(environment.resolve("settings.xml"));
            settings = settings.replace("@CACHE@", xml(temporary.resolve("cache").toString()));
            String publication = System.getenv("ANT_PURIFIER_PUBLICATION_REPOSITORY");
            settings = settings.replace("@PUBLICATIONS@", xml(publication == null ? temporary.resolve("publications").toString() : publication));
            Files.writeString(temporary.resolve("settings.xml"), settings);
            Runtime.getRuntime().addShutdownHook(new Thread(() -> {
                try (var files = Files.walk(temporary)) {
                    files.sorted(Comparator.reverseOrder()).forEach(path -> {
                        try { Files.deleteIfExists(path); } catch (IOException ignored) { }
                    });
                } catch (IOException ignored) { }
            }));
        } catch (IOException error) { throw new BuildException("Cannot activate locked Ivy", error); }
    }
    private static String xml(String value) {
        return value.replace("&", "&amp;").replace("\"", "&quot;").replace("<", "&lt;").replace(">", "&gt;");
    }
    private static boolean isA(Object object, String name) {
        for (Class<?> type = object.getClass(); type != null; type = type.getSuperclass())
            if (type.getName().equals(name)) return true;
        return false;
    }
    @Override public synchronized void taskStarted(BuildEvent event) {
        if (environment == null) return;
        Object task = event.getTask();
        if (task instanceof UnknownElement) {
            UnknownElement element = (UnknownElement)task;
            element.maybeConfigure();
            task = element.getRealThing();
        }
        if (task == null) return;
        if ("1".equals(System.getenv("ANT_PURIFIER_REPRODUCIBLE")) && task instanceof org.apache.tools.ant.taskdefs.Zip)
            ((org.apache.tools.ant.taskdefs.Zip)task).setModificationtime("1980-01-01T00:00:02Z");
        if (!isA(task, "org.apache.ivy.ant.IvyTask")) return;
        try {
            Project project = event.getProject();
            Path base = project.getBaseDir().toPath().toRealPath();
            if (projectRoot == null) projectRoot = base;
            if (!projectRoot.toRealPath().equals(base)) throw new BuildException("Multiple Ant project base directories need separate locks");
            ClassLoader loader = task.getClass().getClassLoader();
            Map<ClassLoader, Reference> projectReferences = references.computeIfAbsent(project, ignored -> new IdentityHashMap<>());
            Reference reference = projectReferences.get(loader);
            if (reference == null) {
                Class<?> type = Class.forName("org.apache.ivy.ant.IvyAntSettings", true, loader);
                Object settings = type.getConstructor().newInstance();
                type.getMethod("setProject", Project.class).invoke(settings, project);
                type.getMethod("setFile", File.class).invoke(settings, temporary.resolve("settings.xml").toFile());
                String id = "nix-purifier-ivy-" + projectReferences.size();
                type.getMethod("setId", String.class).invoke(settings, id);
                reference = new Reference(project, id);
                projectReferences.put(loader, reference);
            }
            task.getClass().getMethod("setSettingsRef", Reference.class).invoke(task, reference);
            if (isA(task, "org.apache.ivy.ant.IvyResolve") || isA(task, "org.apache.ivy.ant.IvyPostResolveTask")) {
                try {
                    if (Boolean.TRUE.equals(task.getClass().getMethod("isInline").invoke(task)))
                        throw new BuildException("Locked inline Ivy resolution is not supported; declare dependencies in ivy.xml");
                } catch (NoSuchMethodException ignored) { }
                File declared = (File)task.getClass().getMethod("getFile").invoke(task);
                String ivyFile = System.getenv("ANT_PURIFIER_IVY_FILE");
                File expected = ivyFile == null ? new File(project.getBaseDir(), "ivy.xml") : new File(ivyFile);
                if (declared != null && !declared.getCanonicalFile().equals(expected.getCanonicalFile()))
                    throw new BuildException("Multiple Ivy project descriptors are not supported yet");
                task.getClass().getMethod("setFile", File.class).invoke(task, environment.resolve("ivy.lock.xml").toFile());
            }
            if ("1".equals(System.getenv("ANT_PURIFIER_REPRODUCIBLE")) &&
                (isA(task, "org.apache.ivy.ant.IvyPublish") || isA(task, "org.apache.ivy.ant.IvyDeliver")))
                task.getClass().getMethod("setPubdate", String.class).invoke(task, "19700101000001");
            if (isA(task, "org.apache.ivy.ant.IvyPublish") && System.getenv("ANT_PURIFIER_PUBLICATION_REPOSITORY") != null)
                task.getClass().getMethod("setResolver", String.class).invoke(task, "purifier-publications");
        } catch (ReflectiveOperationException | IOException error) {
            throw new BuildException("Cannot bind native Ivy task to locked dependencies", error);
        }
    }
    @Override public void buildStarted(BuildEvent event) { if (environment != null) event.getProject().addReference("nix-purifier.active", this); }
    @Override public void buildFinished(BuildEvent event) { }
    @Override public void targetStarted(BuildEvent event) { }
    @Override public void targetFinished(BuildEvent event) { }
    @Override public void taskFinished(BuildEvent event) { }
    @Override public void messageLogged(BuildEvent event) { }
}
