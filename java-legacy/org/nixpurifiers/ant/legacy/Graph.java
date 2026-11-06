// SPDX-License-Identifier: MIT
package org.nixpurifiers.ant.legacy;

import java.io.*;
import java.util.*;
import org.w3c.dom.*;
import org.apache.ivy.core.cache.*;
import org.apache.ivy.core.module.descriptor.*;
import org.apache.ivy.core.module.id.*;
import org.apache.ivy.core.report.*;
import org.apache.ivy.core.resolve.IvyNode;
import org.apache.ivy.core.settings.IvySettings;
import org.apache.ivy.plugins.matcher.*;
import org.apache.ivy.plugins.parser.xml.*;

/** Export native Ivy 2.4 results; no resolver or conflict algorithm lives here. */
final class Graph {
    static String key(ModuleId id) { return id.getOrganisation() + ":" + id.getName(); }
    static String component(String value) {
        if (value == null || !value.matches("[A-Za-z0-9][A-Za-z0-9_.+\\-]*") || value.equals(".."))
            throw new IllegalArgumentException("Unsupported legacy Ivy coordinate: " + value);
        return value;
    }
    private static Map<String, String> declarations(ModuleDescriptor descriptor) {
        Map<String, String> result = new TreeMap<String, String>();
        for (DependencyDescriptor dependency : descriptor.getDependencies()) {
            String id = key(dependency.getDependencyId());
            ModuleRevisionId requested = dependency.getDynamicConstraintDependencyRevisionId();
            String revision = (requested == null ? dependency.getDependencyRevisionId() : requested).toString();
            result.put(id, result.containsKey(id) ? result.get(id) + ";" + revision : revision);
        }
        return result;
    }
    static void isolate(IvySettings settings, File output) {
        settings.setDefaultCache(new File(output, "cache"));
        int index = 0;
        for (RepositoryCacheManager manager : settings.getRepositoryCacheManagers()) {
            if (!(manager instanceof DefaultRepositoryCacheManager))
                throw new IllegalArgumentException("Custom legacy Ivy caches are unsupported");
            ((DefaultRepositoryCacheManager)manager).setBasedir(new File(output, "cache/repository-" + index++));
        }
        if (!(settings.getResolutionCacheManager() instanceof DefaultResolutionCacheManager))
            throw new IllegalArgumentException("Custom legacy Ivy resolution caches are unsupported");
        ((DefaultResolutionCacheManager)settings.getResolutionCacheManager()).setBasedir(new File(output, "cache/resolution"));
    }
    static DefaultModuleDescriptor pinned(IvySettings settings, File input, File previousFile,
            boolean updateAll, Set<String> updated, Set<String> previousSelected) throws Exception {
        DefaultModuleDescriptor descriptor = (DefaultModuleDescriptor)XmlModuleDescriptorParser.getInstance()
            .parseDescriptor(settings, input.toURI().toURL(), true);
        if (descriptor.getInheritedDescriptors().length != 0)
            throw new IllegalArgumentException("Legacy Ivy extends descriptors are unsupported");
        if (!updateAll && previousFile.isFile()) {
            DefaultModuleDescriptor previous = (DefaultModuleDescriptor)XmlModuleDescriptorParser.getInstance()
                .parseDescriptor(settings, previousFile.toURI().toURL(), true);
            Map<String, String> old = declarations(previous), current = declarations(descriptor);
            for (Object object : previous.getAllDependencyDescriptorMediators().getAllRules().entrySet()) {
                Map.Entry rule = (Map.Entry)object;
                if (!(rule.getValue() instanceof OverrideDependencyDescriptorMediator)) continue;
                MapMatcher matcher = (MapMatcher)rule.getKey();
                String org = (String)matcher.getAttributes().get("organisation");
                String module = (String)matcher.getAttributes().get("module");
                String id = org + ":" + module;
                if (!previousSelected.contains(id) || !"exact".equals(matcher.getPatternMatcher().getName()) || updated.contains(id)) continue;
                if (current.containsKey(id) && !current.get(id).equals(old.get(id))) continue;
                descriptor.addDependencyDescriptorMediator(ModuleId.newInstance(org, module), ExactPatternMatcher.INSTANCE,
                    (OverrideDependencyDescriptorMediator)rule.getValue());
            }
        }
        return descriptor;
    }
    static void writePinned(DefaultModuleDescriptor descriptor, File destination) throws Exception {
        IO.mkdir(destination.getAbsoluteFile().getParentFile());
        XmlModuleDescriptorWriter.write(descriptor, destination);
        Document document = IO.parse(destination);
        NodeList dependencies = document.getElementsByTagName("dependency");
        for (int index = 0; index < dependencies.getLength(); index++) {
            Element dependency = (Element)dependencies.item(index);
            for (DependencyDescriptor original : descriptor.getDependencies()) {
                if (!original.getDependencyId().getOrganisation().equals(dependency.getAttribute("org")) ||
                    !original.getDependencyId().getName().equals(dependency.getAttribute("name"))) continue;
                DependencyDescriptor mediated = descriptor.mediate(original);
                if (!mediated.getDependencyRevisionId().equals(original.getDependencyRevisionId())) {
                    if (!dependency.hasAttribute("revConstraint")) dependency.setAttribute("revConstraint", dependency.getAttribute("rev"));
                    dependency.setAttribute("rev", mediated.getDependencyRevisionId().getRevision());
                }
                break;
            }
        }
        IO.xml(document, destination);
    }
    static Document export(IvySettings settings, File input, File output, ResolveReport report) throws Exception {
        Locale.setDefault(Locale.ROOT);
        if (report.hasError()) throw new IOException(report.getAllProblemMessages().toString());
        Document document = IO.document();
        Element result = document.createElement("resolution"); document.appendChild(result);
        Guard.observe(document, result);
        Element modules = IO.element(document, result, "modules");
        Element artifacts = IO.element(document, result, "artifacts");
        // Maven projections are deliberately not part of this profile.
        IO.element(document, result, "metadata");
        TreeMap<String, IvyNode> selected = new TreeMap<String, IvyNode>();
        for (Object object : report.getDependencies()) {
            IvyNode node = (IvyNode)object;
            if (node.isCompletelyEvicted() || node.getModuleRevision() == null) continue;
            ModuleRevisionId id = node.getResolvedId();
            if (id.getBranch() != null) throw new IllegalArgumentException("Legacy Ivy branches are unsupported");
            String key = key(id.getModuleId());
            IvyNode existing = selected.get(key);
            if (existing != null && !existing.getResolvedId().equals(id))
                throw new IllegalArgumentException("Multiple selected legacy revisions of " + key);
            selected.put(key, node);
        }
        DefaultModuleDescriptor descriptor = (DefaultModuleDescriptor)XmlModuleDescriptorParser.getInstance()
            .parseDescriptor(settings, input.toURI().toURL(), true);
        for (Map.Entry<String, IvyNode> entry : selected.entrySet()) {
            IvyNode node = entry.getValue(); ModuleRevisionId id = node.getResolvedId();
            String org = component(id.getOrganisation()), name = component(id.getName()), version = component(id.getRevision());
            String location = org.replace('.', '/') + "/" + name + "/" + version;
            File file = new File(output, "modules/" + location + "/ivy.xml"); IO.mkdir(file.getParentFile());
            ModuleDescriptor module = node.getModuleRevision().getDescriptor();
            if (module.getInheritedDescriptors().length != 0)
                throw new IllegalArgumentException("Legacy Ivy extends descriptors are unsupported");
            XmlModuleDescriptorWriter.write(module, file);
            Element record = IO.element(document, modules, "module", "group", org, "name", name,
                "version", version, "path", location + "/ivy.xml", "file", file.toString());
            MetadataArtifactDownloadReport metadata = node.getModuleRevision().getReport();
            if (metadata == null || metadata.getArtifactOrigin() == null || metadata.getOriginalLocalFile() == null)
                throw new IOException("Missing native legacy module origin for " + id);
            IO.element(document, record, "original", "url", metadata.getArtifactOrigin().getLocation(),
                "file", metadata.getOriginalLocalFile().toString());
            descriptor.addDependencyDescriptorMediator(id.getModuleId(), ExactPatternMatcher.INSTANCE,
                new OverrideDependencyDescriptorMediator(null, version));
        }
        TreeMap<String, ArtifactDownloadReport> downloads = new TreeMap<String, ArtifactDownloadReport>();
        for (ArtifactDownloadReport download : report.getAllArtifactsReports())
            downloads.put(download.getArtifact().getId().toString(), download);
        for (ArtifactDownloadReport download : downloads.values()) {
            Artifact artifact = download.getArtifact(); ModuleRevisionId id = artifact.getModuleRevisionId();
            IvyNode selection = selected.get(key(id.getModuleId()));
            if (selection == null || !selection.getResolvedId().equals(id)) continue;
            if (artifact.getUrl() != null) throw new IllegalArgumentException("Explicit legacy artifact URLs are unsupported");
            if (download.getLocalFile() == null || download.getArtifactOrigin() == null)
                throw new IOException("Missing native legacy artifact origin for " + artifact);
            String classifier = artifact.getExtraAttribute("classifier");
            if (classifier == null) classifier = ""; else component(classifier);
            String org = component(id.getOrganisation()), module = component(id.getName()), version = component(id.getRevision());
            String name = component(artifact.getName()), extension = component(artifact.getExt());
            String path = org.replace('.', '/') + "/" + module + "/" + version + "/" + name + "-" + version
                + (classifier.length() == 0 ? "" : "-" + classifier) + "." + extension;
            IO.element(document, artifacts, "artifact", "group", org, "module", module, "version", version,
                "name", name, "ext", extension, "type", component(artifact.getType()), "classifier", classifier,
                "path", path, "url", download.getArtifactOrigin().getLocation(), "file", download.getLocalFile().toString());
        }
        descriptor.setResolvedPublicationDate(org.apache.ivy.util.DateUtil.parse("19700101000001"));
        if (descriptor.getModuleRevisionId().getRevision().startsWith("working@")) {
            ModuleRevisionId id = descriptor.getModuleRevisionId();
            ModuleRevisionId stable = ModuleRevisionId.newInstance(id.getOrganisation(), id.getName(), "working");
            descriptor.setModuleRevisionId(stable); descriptor.setResolvedModuleRevisionId(stable);
        }
        writePinned(descriptor, new File(output, "ivy.lock.xml"));
        return document;
    }
}
