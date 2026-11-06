// SPDX-License-Identifier: MIT
package org.nixpurifiers.ant.legacy;

import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import org.apache.tools.ant.*;
import org.apache.tools.ant.taskdefs.Javac;
import org.apache.tools.ant.types.CommandlineJava;
import org.apache.ivy.Ivy;
import org.w3c.dom.*;

final class Guard {
    private static Properties context;
    private static String projectRoot;
    private static final Set<String> PACKAGING = new HashSet<String>(Arrays.asList(
        "org.apache.tools.ant.taskdefs.Zip", "org.apache.tools.ant.taskdefs.Tar",
        "org.apache.tools.ant.taskdefs.Pack", "org.apache.ivy.ant.IvyPublish", "org.apache.ivy.ant.IvyDeliver"));
    static Properties context() throws Exception {
        if (context == null) {
            String file = System.getenv("ANT_PURIFIER_LEGACY_PROPERTIES");
            if (file == null) throw new BuildException("ant-purifier: legacy runtime context is missing");
            context = IO.properties(new File(file));
            if (!"legacy-basic-v1".equals(context.getProperty("profile")))
                throw new BuildException("ant-purifier: unsupported legacy runtime context");
        }
        return context;
    }
    static String expected(String key) throws Exception {
        String value = context().getProperty(key);
        if (value == null || value.length() == 0) throw new BuildException("ant-purifier: missing legacy context field " + key);
        return value;
    }
    private static String origin(Class<?> type) throws Exception {
        if (type.getProtectionDomain().getCodeSource() == null)
            throw new BuildException("ant-purifier: missing native class origin " + type.getName());
        return IO.canonical(new File(type.getProtectionDomain().getCodeSource().getLocation().toURI()));
    }
    static void origin(Class<?> type, String key) throws Exception {
        if (!origin(type).equals(IO.canonical(new File(expected(key)))))
            throw new BuildException("ant-purifier: actual " + key + " differs from its source-owned legacy runtime");
    }
    static void validate(File root) throws Exception {
        if (!IO.canonical(new File("/proc/self/exe")).equals(IO.canonical(new File(expected("manager.executable")))))
            throw new BuildException("ant-purifier: actual legacy manager executable differs");
        if (!IO.canonical(new File(System.getProperty("java.home"))).equals(IO.canonical(new File(expected("manager.runtimeHome")))))
            throw new BuildException("ant-purifier: actual legacy manager runtime home differs");
        origin(Project.class, "ant.jar"); origin(Ivy.class, "ivy.jar"); origin(Guard.class, "collector.jar");
        if (org.apache.tools.ant.Main.getAntVersion().indexOf("version " + expected("ant.version") + " ") < 0)
            throw new BuildException("ant-purifier: native Ant version differs from its declared source");
        if (!Ivy.getIvyVersion().equals(expected("ivy.version")))
            throw new BuildException("ant-purifier: native Ivy version differs from its declared source");
        String captured = System.getenv("ANT_PURIFIER_LEGACY_CAPTURED");
        if (captured != null) {
            Properties observation = IO.properties(new File(captured));
            Map<String, String> actual = new HashMap<String, String>();
            actual.put("contextHash", expected("context.hash"));
            actual.put("sdkIdentity", expected("sdk.identity"));
            actual.put("managerIdentity", expected("manager.identity"));
            actual.put("executable", IO.canonical(new File("/proc/self/exe")));
            actual.put("runtimeHome", IO.canonical(new File(System.getProperty("java.home"))));
            actual.put("javaVersion", System.getProperty("java.version"));
            actual.put("antVersion", expected("ant.version")); actual.put("ivyVersion", Ivy.getIvyVersion());
            actual.put("antJar", origin(Project.class)); actual.put("ivyJar", origin(Ivy.class));
            actual.put("collectorJar", origin(Guard.class));
            for (Map.Entry<String, String> entry : actual.entrySet())
                if (!entry.getValue().equals(observation.getProperty(entry.getKey())))
                    throw new BuildException("ant-purifier: captured native legacy origin differs: " + entry.getKey());
        }
        projectRoot = IO.canonical(root);
    }
    static boolean isA(Class<?> type, String name) {
        for (; type != null; type = type.getSuperclass()) if (type.getName().equals(name)) return true;
        return false;
    }
    static void supported(Class<?> type) {
        if (TaskContainer.class.isAssignableFrom(type))
            throw new BuildException("ant-purifier: legacy-basic-v1 does not support task containers");
        for (String name : PACKAGING) if (isA(type, name))
            throw new BuildException("ant-purifier: legacy-basic-v1 does not support packaging or publication tasks");
        if (isA(type, "org.apache.tools.ant.taskdefs.Ant") || isA(type, "org.apache.tools.ant.taskdefs.CallTarget"))
            throw new BuildException("ant-purifier: legacy-basic-v1 does not support nested Ant projects");
        if (isA(type, "org.apache.tools.ant.taskdefs.Javadoc") || isA(type, "org.apache.tools.ant.taskdefs.optional.junit.JUnitTask"))
            throw new BuildException("ant-purifier: this legacy task runtime has not been captured by legacy-basic-v1");
    }
    static Object task(BuildEvent event) throws Exception {
        Object task = event.getTask();
        // Ant 1.5 fires taskStarted before Task.perform calls maybeConfigure.
        // Configure every task before inspecting attributes or replacing Ivy inputs.
        if (task instanceof Task) ((Task)task).maybeConfigure();
        if (task instanceof UnknownElement) task = ((UnknownElement)task).getTask();
        if (task == null) return null;
        supported(task.getClass());
        if (projectRoot != null && !projectRoot.equals(IO.canonical(event.getProject().getBaseDir())))
            throw new BuildException("ant-purifier: legacy-basic-v1 requires one native project root");
        for (Class<?> type = task.getClass(); type != null; type = type.getSuperclass())
            if (type.getName().equals("org.apache.ivy.ant.IvyTask")) origin(type, "ivy.jar");
        if (task instanceof Javac) {
            Javac javac = (Javac)task;
            if (javac.isForkedJavac()) {
                if (!IO.canonical(new File(javac.getJavacExecutable())).equals(IO.canonical(new File(expected("compiler.executable")))))
                    throw new BuildException("ant-purifier: legacy compiler differs from the declared SDK");
            } else {
                String compiler = javac.getCompiler();
                if (!("modern".equals(compiler) || (compiler != null && compiler.startsWith("javac"))))
                    throw new BuildException("ant-purifier: legacy-basic-v1 requires the declared JDK compiler");
                origin(Class.forName("com.sun.tools.javac.Main"), "compiler.jar");
            }
        }
        if (task instanceof org.apache.tools.ant.taskdefs.Java) {
            Field fork = org.apache.tools.ant.taskdefs.Java.class.getDeclaredField("fork"); fork.setAccessible(true);
            if (fork.getBoolean(task)) {
                Field command = org.apache.tools.ant.taskdefs.Java.class.getDeclaredField("cmdl"); command.setAccessible(true);
                String executable = ((CommandlineJava)command.get(task)).getCommandline()[0];
                String canonical = IO.canonical(new File(executable));
                if (!new File(executable).isAbsolute() ||
                    !(canonical.equals(IO.canonical(new File(expected("manager.executable")))) ||
                      canonical.equals(IO.canonical(new File(expected("manager.runtimeHome"), "bin/java")))))
                    throw new BuildException("ant-purifier: legacy Java task runtime differs from the declared SDK");
            }
        }
        return task;
    }
    private static void inspect(Project project, String name, Set<String> seen, int[] resolves) {
        if (!seen.add(name)) return;
        Target target = (Target)project.getTargets().get(name);
        if (target == null) throw new BuildException("ant-purifier: missing legacy target " + name);
        Enumeration dependencies = target.getDependencies();
        while (dependencies.hasMoreElements()) inspect(project, (String)dependencies.nextElement(), seen, resolves);
        for (Task task : target.getTasks()) {
            Class<?> type = task.getClass();
            if (task instanceof UnknownElement) {
                type = (Class<?>)project.getTaskDefinitions().get(((UnknownElement)task).getTag());
                if (type == null) throw new BuildException("ant-purifier: legacy task definitions must precede selected targets");
            }
            supported(type);
            if (isA(type, "org.apache.ivy.ant.IvyResolve")) resolves[0]++;
        }
    }
    static void preflight(Project project, String[] targets, boolean capture) {
        int[] resolves = new int[]{0}; Set<String> seen = new HashSet<String>();
        for (String name : targets) inspect(project, name, seen, resolves);
        if (capture && resolves[0] != 1)
            throw new BuildException("ant-purifier: legacy capture requires exactly one native Ivy resolve task");
    }
    static void observe(Document document, Element parent) throws Exception {
        IO.element(document, parent, "runtime", "contextHash", expected("context.hash"),
            "sdkIdentity", expected("sdk.identity"), "managerIdentity", expected("manager.identity"),
            "executable", IO.canonical(new File("/proc/self/exe")),
            "runtimeHome", IO.canonical(new File(System.getProperty("java.home"))),
            "javaVersion", System.getProperty("java.version"), "antVersion", expected("ant.version"),
            "ivyVersion", Ivy.getIvyVersion(), "antJar", origin(Project.class), "ivyJar", origin(Ivy.class),
            "collectorJar", origin(Guard.class));
    }
}
