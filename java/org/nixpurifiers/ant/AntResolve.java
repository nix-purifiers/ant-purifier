// SPDX-License-Identifier: MIT
package org.nixpurifiers.ant;

import java.io.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import org.apache.tools.ant.*;
import org.apache.ivy.Ivy;
import org.apache.ivy.ant.IvyTask;
import org.apache.ivy.ant.IvyResolve;
import org.apache.ivy.core.module.descriptor.DefaultModuleDescriptor;
import org.apache.ivy.core.report.ResolveReport;
import org.apache.ivy.core.settings.IvySettings;
import org.apache.ivy.plugins.parser.xml.XmlModuleDescriptorWriter;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.transform.*;
import javax.xml.transform.dom.DOMSource;
import javax.xml.transform.stream.StreamResult;
import org.w3c.dom.*;

/** Run the project's normal resolver target, including its native property setup. */
public final class AntResolve implements BuildListener {
    private final File input, previous;
    private final Path output;
    private final boolean updateAll;
    private final Set<String> updated, previousSelected;
    private IvySettings settings;
    private ResolveReport report;
    private int resolutions;
    private AntResolve(String[] args) {
        input = new File(args[0]); output = Path.of(args[1]); previous = new File(args[2]);
        updateAll = args[3].equals("all");
        updated = new HashSet<>(Arrays.asList(args[4].split(",")));
        previousSelected = new HashSet<>(Arrays.asList(args[5].split(",")));
    }
    @Override public void taskStarted(BuildEvent event) {
        Object task = event.getTask();
        if (task instanceof UnknownElement) {
            UnknownElement element = (UnknownElement)task;
            element.maybeConfigure(); task = element.getRealThing();
        }
        if (!(task instanceof IvyResolve)) return;
        IvyResolve resolve = (IvyResolve)task;
        try {
            Path base = Path.of(System.getProperty("user.dir")).toRealPath();
            if (!event.getProject().getBaseDir().toPath().toRealPath().equals(base)) throw new BuildException("Multiple Ant project base directories need separate locks; choose the project root with --project");
            if (resolve.isInline()) throw new BuildException("Declare locked project dependencies in ivy.xml; inline Ivy resolution is not supported yet");
            File declared = resolve.getFile();
            if (declared != null && !declared.getCanonicalFile().equals(input.getCanonicalFile()))
                throw new BuildException("Multiple Ivy project descriptors are not supported yet");
            Method getter = IvyTask.class.getDeclaredMethod("getIvyInstance"); getter.setAccessible(true);
            Ivy ivy = (Ivy)getter.invoke(resolve); settings = ivy.getSettings();
            Resolve.isolate(settings, output);
            DefaultModuleDescriptor descriptor = Resolve.pinned(settings, input, previous, updateAll, updated, previousSelected);
            descriptor.setResolvedPublicationDate(new Date(1000));
            File pinned = output.resolve("input-" + resolutions++ + ".xml").toFile();
            Resolve.writePinned(descriptor, pinned);
            resolve.setFile(pinned); resolve.setConf("*"); resolve.setKeep(true);
            resolve.setHaltonfailure(true);
            resolve.setRefresh(updateAll || !updated.equals(Set.of("")));
        } catch (Exception error) { throw new BuildException("Cannot prepare native locked Ivy resolution", error); }
    }
    @Override public void taskFinished(BuildEvent event) {
        if (event.getException() != null) return;
        Object value = event.getProject().getReference("ivy.resolved.report");
        if (value instanceof ResolveReport) report = (ResolveReport)value;
    }
    private static void sourceRoots(Project project, RuntimeConfigurable wrapper, Set<String> roots) {
        String tag = wrapper.getElementTag();
        if (tag.equals("javac") || tag.endsWith(":javac")) {
            Object source = wrapper.getAttributeMap().get("srcdir");
            if (source != null) {
                String expanded = project.replaceProperties(source.toString());
                if (!expanded.contains("${") && !expanded.contains("@{")) {
                    Path base = project.getBaseDir().toPath().toAbsolutePath().normalize();
                    for (String directory : new org.apache.tools.ant.types.Path(project, expanded).list()) {
                        Path path = Path.of(directory).toAbsolutePath().normalize();
                        if (path.startsWith(base)) {
                            String relative = base.relativize(path).toString();
                            roots.add(relative.isEmpty() ? "." : relative);
                        }
                    }
                }
            }
        }
        for (var children = wrapper.getChildren(); children.hasMoreElements();)
            sourceRoots(project, children.nextElement(), roots);
    }
    private static void exportSourceRoots(Project project, Path output) throws Exception {
        Set<String> roots = new TreeSet<>();
        for (Target target : project.getTargets().values())
            for (Task task : target.getTasks()) sourceRoots(project, task.getRuntimeConfigurableWrapper(), roots);
        Document doc = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(output.resolve("resolution.xml").toFile());
        Element list = doc.createElement("sourceRoots"); doc.getDocumentElement().appendChild(list);
        for (String root : roots) { Element item = doc.createElement("source"); item.setAttribute("path", root); list.appendChild(item); }
        Transformer transformer = TransformerFactory.newInstance().newTransformer();
        transformer.setOutputProperty(OutputKeys.INDENT, "yes");
        transformer.transform(new DOMSource(doc), new StreamResult(output.resolve("resolution.xml").toFile()));
    }
    public static void main(String[] args) throws Exception {
        AntResolve recorder = new AntResolve(args);
        Files.createDirectories(recorder.output);
        File buildFile = new File(args[6]); String target = args[7];
        Project project = new Project(); project.init();
        DefaultLogger logger = new DefaultLogger();
        logger.setErrorPrintStream(System.err); logger.setOutputPrintStream(System.err);
        logger.setMessageOutputLevel(Project.MSG_INFO); project.addBuildListener(logger);
        project.addBuildListener(recorder);
        for (int index = 8; index < args.length; index++) {
            String[] property = args[index].split("=", 2);
            if (property.length != 2) throw new IllegalArgumentException("Expected Ant property NAME=VALUE");
            project.setUserProperty(property[0], property[1]);
        }
        ProjectHelper.configureProject(project, buildFile);
        if (!project.getTargets().containsKey(target)) throw new BuildException("No Ant target '" + target + "'; select the existing dependency resolver with --resolve-target");
        project.executeTarget(target);
        if (recorder.report == null || recorder.settings == null)
            throw new BuildException("The selected target did not execute ivy:resolve");
        Resolve.exportNative(recorder.settings, recorder.input, recorder.output, recorder.report);
        exportSourceRoots(project, recorder.output);
    }
    @Override public void buildStarted(BuildEvent event) { }
    @Override public void buildFinished(BuildEvent event) { }
    @Override public void targetStarted(BuildEvent event) { }
    @Override public void targetFinished(BuildEvent event) { }
    @Override public void messageLogged(BuildEvent event) { }
}
