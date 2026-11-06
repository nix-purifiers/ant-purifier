// SPDX-License-Identifier: MIT
package org.nixpurifiers.ant.legacy;

import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import org.apache.tools.ant.*;
import org.apache.ivy.Ivy;
import org.apache.ivy.ant.*;
import org.apache.ivy.core.module.descriptor.DefaultModuleDescriptor;
import org.apache.ivy.core.report.ResolveReport;
import org.apache.ivy.core.settings.IvySettings;
import org.w3c.dom.*;
import org.xml.sax.AttributeList;

/** Observe the selected original native target on the declared Java 6 SDK. */
public final class NativeResolve implements BuildListener {
    private final File input, output, previous;
    private final boolean updateAll;
    private final Set<String> updated, previousSelected;
    private IvySettings settings;
    private Ivy nativeIvy;
    private ResolveReport report;
    private int resolutions;
    private NativeResolve(String[] args) {
        input = new File(args[0]); output = new File(args[1]); previous = new File(args[2]);
        updateAll = args[3].equals("all");
        updated = new HashSet<String>(Arrays.asList(args[4].split(",")));
        updated.remove("");
        previousSelected = new HashSet<String>(Arrays.asList(args[5].split(",")));
        previousSelected.remove("");
    }
    public void taskStarted(BuildEvent event) {
        try {
            Object task = Guard.task(event);
            if (!(task instanceof IvyResolve)) return;
            if (resolutions++ != 0) throw new BuildException("ant-purifier: legacy capture requires one native resolution");
            IvyResolve resolve = (IvyResolve)task;
            if (resolve.isInline()) throw new BuildException("ant-purifier: legacy inline resolution is unsupported");
            File declared = resolve.getFile();
            if (declared != null && !declared.getCanonicalFile().equals(input.getCanonicalFile()))
                throw new BuildException("ant-purifier: multiple legacy Ivy descriptors are unsupported");
            Method getter = IvyTask.class.getDeclaredMethod("getIvyInstance"); getter.setAccessible(true);
            Ivy ivy = (Ivy)getter.invoke(resolve); nativeIvy = ivy; settings = ivy.getSettings();
            Graph.isolate(settings, output);
            // Ivy 2.4 parsers consult their native thread context as well as arguments.
            ivy.pushContext();
            try {
                DefaultModuleDescriptor descriptor = Graph.pinned(settings, input, previous, updateAll, updated, previousSelected);
                descriptor.setResolvedPublicationDate(new Date(1000));
                File pinned = new File(output, "input.xml"); Graph.writePinned(descriptor, pinned);
                resolve.setFile(pinned); resolve.setKeep(true); resolve.setHaltonfailure(true);
                resolve.setRefresh(updateAll || !updated.isEmpty());
            } finally { ivy.popContext(); }
        } catch (BuildException error) { throw error; }
        catch (Exception error) { throw new BuildException("Cannot prepare native legacy Ivy resolution", error); }
    }
    public void taskFinished(BuildEvent event) {
        if (event.getException() != null) return;
        Object value = event.getProject().getReference("ivy.resolved.report");
        if (value instanceof ResolveReport) report = (ResolveReport)value;
    }
    private static void roots(Project project, RuntimeConfigurable wrapper, Set<String> roots) throws Exception {
        if (wrapper == null) return;
        String tag = wrapper.getElementTag();
        if ("javac".equals(tag) || (tag != null && tag.endsWith(":javac"))) {
            AttributeList attributes = wrapper.getAttributes();
            String source = attributes == null ? null : attributes.getValue("srcdir");
            if (source != null) {
                String expanded = project.replaceProperties(source);
                if (expanded.indexOf("${") < 0 && expanded.indexOf("@{") < 0) {
                    String base = IO.canonical(project.getBaseDir());
                    for (String directory : new org.apache.tools.ant.types.Path(project, expanded).list()) {
                        String path = IO.canonical(new File(directory));
                        if (path.equals(base)) roots.add(".");
                        else if (path.startsWith(base + File.separator)) roots.add(path.substring(base.length() + 1));
                    }
                }
            }
        }
        Method children = RuntimeConfigurable.class.getDeclaredMethod("getChildren"); children.setAccessible(true);
        Enumeration values = (Enumeration)children.invoke(wrapper);
        while (values != null && values.hasMoreElements()) roots(project, (RuntimeConfigurable)values.nextElement(), roots);
    }
    public static void main(String[] args) throws Exception {
        if (args.length < 8) throw new IllegalArgumentException("Missing legacy capture arguments");
        Guard.validate(new File(System.getProperty("user.dir")));
        NativeResolve recorder = new NativeResolve(args); IO.mkdir(recorder.output);
        Project project = new Project(); project.init();
        DefaultLogger logger = new DefaultLogger();
        logger.setErrorPrintStream(System.err); logger.setOutputPrintStream(System.err);
        logger.setMessageOutputLevel(Project.MSG_INFO); project.addBuildListener(logger); project.addBuildListener(recorder);
        for (int index = 8; index < args.length; index++) {
            String[] property = args[index].split("=", 2);
            if (property.length != 2) throw new IllegalArgumentException("Expected native property NAME=VALUE");
            project.setUserProperty(property[0], property[1]);
        }
        ProjectHelper.configureProject(project, new File(args[6]));
        Guard.preflight(project, new String[]{args[7]}, true);
        project.executeTarget(args[7]);
        if (recorder.report == null || recorder.settings == null)
            throw new BuildException("The selected legacy target did not execute native Ivy resolve");
        Document document;
        recorder.nativeIvy.pushContext();
        try { document = Graph.export(recorder.settings, recorder.input, recorder.output, recorder.report); }
        finally { recorder.nativeIvy.popContext(); }
        Set<String> sourceRoots = new TreeSet<String>();
        for (Object object : project.getTargets().values())
            for (Task task : ((Target)object).getTasks()) roots(project, task.getRuntimeConfigurableWrapper(), sourceRoots);
        Element list = IO.element(document, document.getDocumentElement(), "sourceRoots");
        for (String path : sourceRoots) IO.element(document, list, "source", "path", path);
        IO.xml(document, new File(recorder.output, "resolution.xml"));
    }
    public void buildStarted(BuildEvent event) { }
    public void buildFinished(BuildEvent event) { }
    public void targetStarted(BuildEvent event) { }
    public void targetFinished(BuildEvent event) { }
    public void messageLogged(BuildEvent event) { }
}
