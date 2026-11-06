// SPDX-License-Identifier: MIT
package org.nixpurifiers.ant.legacy;

import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import org.apache.tools.ant.*;
import org.apache.tools.ant.types.Reference;

/** Bind native Ivy tasks to the prefetched repository without replacing Ant. */
public final class NativeReplay implements BuildListener {
    private final File environment, temporary;
    private final Map<Project, Map<ClassLoader, Reference>> references =
        new IdentityHashMap<Project, Map<ClassLoader, Reference>>();
    private boolean preflighted;
    public NativeReplay() {
        try {
            String root = System.getenv("ANT_PURIFIER_PROJECT_ROOT");
            Guard.validate(new File(root == null ? System.getProperty("user.dir") : root));
            String selected = System.getenv("ANT_PURIFIER_ENVIRONMENT");
            if (selected == null) throw new BuildException("ant-purifier: missing legacy dependency environment");
            environment = new File(selected); temporary = IO.temporaryDirectory().getCanonicalFile();
            String settings = IO.read(new File(environment, "settings.xml"));
            settings = settings.replace("@CACHE@", xml(new File(temporary, "cache").toString()));
            settings = settings.replace("@PUBLICATIONS@", xml(new File(temporary, "unsupported-publications").toString()));
            IO.write(new File(temporary, "settings.xml"), settings);
            final File owned = temporary; final String canonical = temporary.getCanonicalPath();
            Runtime.getRuntime().addShutdownHook(new Thread(new Runnable() {
                public void run() { IO.delete(owned, canonical); }
            }));
        } catch (BuildException error) { throw error; }
        catch (Exception error) { throw new BuildException("Cannot activate native legacy Ivy replay", error); }
    }
    private static String xml(String value) {
        return value.replace("&", "&amp;").replace("\"", "&quot;").replace("<", "&lt;").replace(">", "&gt;");
    }
    public synchronized void taskStarted(BuildEvent event) {
        try {
            Object task = Guard.task(event);
            if (task == null || !Guard.isA(task.getClass(), "org.apache.ivy.ant.IvyTask")) return;
            Project project = event.getProject(); ClassLoader loader = task.getClass().getClassLoader();
            Map<ClassLoader, Reference> projectReferences = references.get(project);
            if (projectReferences == null) {
                projectReferences = new IdentityHashMap<ClassLoader, Reference>(); references.put(project, projectReferences);
            }
            Reference reference = projectReferences.get(loader);
            if (reference == null) {
                Class<?> type = Class.forName("org.apache.ivy.ant.IvyAntSettings", true, loader);
                Object settings = type.getConstructor().newInstance();
                type.getMethod("setProject", Project.class).invoke(settings, project);
                type.getMethod("setFile", File.class).invoke(settings, new File(temporary, "settings.xml"));
                String id = "nix-legacy-ivy-" + projectReferences.size();
                type.getMethod("setId", String.class).invoke(settings, id);
                reference = new Reference(id); projectReferences.put(loader, reference);
            }
            task.getClass().getMethod("setSettingsRef", Reference.class).invoke(task, reference);
            if (Guard.isA(task.getClass(), "org.apache.ivy.ant.IvyResolve") ||
                Guard.isA(task.getClass(), "org.apache.ivy.ant.IvyPostResolveTask")) {
                if (Boolean.TRUE.equals(task.getClass().getMethod("isInline").invoke(task)))
                    throw new BuildException("ant-purifier: legacy inline resolution is unsupported");
                File declared = (File)task.getClass().getMethod("getFile").invoke(task);
                String ivy = System.getenv("ANT_PURIFIER_IVY_FILE");
                File expected = ivy == null ? new File(project.getBaseDir(), "ivy.xml") : new File(ivy);
                if (declared != null && !declared.getCanonicalFile().equals(expected.getCanonicalFile()))
                    throw new BuildException("ant-purifier: multiple legacy Ivy descriptors are unsupported");
                task.getClass().getMethod("setFile", File.class).invoke(task, new File(environment, "ivy.lock.xml"));
            }
        } catch (BuildException error) { throw error; }
        catch (Exception error) { throw new BuildException("Cannot bind native legacy Ivy task", error); }
    }
    public void targetStarted(BuildEvent event) {
        if (!preflighted) {
            String targets = System.getenv("ANT_PURIFIER_LEGACY_TARGETS");
            String[] selected = targets == null || targets.length() == 0
                ? new String[]{event.getProject().getDefaultTarget()} : targets.split("\n");
            Guard.preflight(event.getProject(), selected, false); preflighted = true;
        }
    }
    public void buildStarted(BuildEvent event) { }
    public void buildFinished(BuildEvent event) { }
    public void targetFinished(BuildEvent event) { }
    public void taskFinished(BuildEvent event) { }
    public void messageLogged(BuildEvent event) { }
}
