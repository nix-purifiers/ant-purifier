// SPDX-License-Identifier: MIT
package org.nixpurifiers.ant;

import java.io.*;
import java.nio.file.*;
import java.util.*;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.transform.*;
import javax.xml.transform.dom.DOMSource;
import javax.xml.transform.stream.StreamResult;
import org.w3c.dom.*;
import org.apache.ivy.Ivy;
import org.apache.ivy.core.module.descriptor.*;
import org.apache.ivy.core.module.id.*;
import org.apache.ivy.core.resolve.*;
import org.apache.ivy.core.report.*;
import org.apache.ivy.core.settings.IvySettings;
import org.apache.ivy.core.cache.*;
import org.apache.ivy.plugins.matcher.ExactPatternMatcher;
import org.apache.ivy.plugins.parser.xml.*;

/** Use Ivy's resolver and descriptor writer; export only missing transport data. */
public final class Resolve {
    private static String key(ModuleId id) { return id.getOrganisation() + ":" + id.getName(); }
    private static String component(String value) {
        if (value == null || !value.matches("[A-Za-z0-9][A-Za-z0-9_.+\\-]*") || value.equals(".."))
            throw new IllegalArgumentException("Unsupported Ivy coordinate: " + value);
        return value;
    }
    private static Element element(Document doc, Element parent, String name, String... attrs) {
        Element result = doc.createElement(name);
        for (int n = 0; n < attrs.length; n += 2) result.setAttribute(attrs[n], attrs[n + 1]);
        parent.appendChild(result); return result;
    }
    private static Map<String, String> declarations(ModuleDescriptor descriptor) {
        Map<String, String> result = new TreeMap<>();
        for (DependencyDescriptor dependency : descriptor.getDependencies()) {
            String id = key(dependency.getDependencyId());
            ModuleRevisionId requested = dependency.getDynamicConstraintDependencyRevisionId();
            String revision = (requested == null ? dependency.getDependencyRevisionId() : requested).toString();
            result.merge(id, revision, (left, right) -> left + ";" + right);
        }
        return result;
    }
    static void isolate(IvySettings settings, Path output) {
        // Project settings may select a resolver, but never the user's shared cache.
        settings.setDefaultCache(output.resolve("cache").toFile());
        int cacheIndex = 0;
        for (RepositoryCacheManager manager : settings.getRepositoryCacheManagers()) {
            if (!(manager instanceof DefaultRepositoryCacheManager))
                throw new IllegalArgumentException("Custom Ivy cache managers are not supported yet");
            ((DefaultRepositoryCacheManager)manager).setBasedir(output.resolve("cache/repository-" + cacheIndex++).toFile());
        }
        if (settings.getResolutionCacheManager() instanceof DefaultResolutionCacheManager)
            ((DefaultResolutionCacheManager)settings.getResolutionCacheManager()).setBasedir(output.resolve("cache/resolution").toFile());
        else throw new IllegalArgumentException("Custom Ivy resolution caches are not supported yet");
    }
    static DefaultModuleDescriptor pinned(IvySettings settings, File input, File previousFile,
                                           boolean updateAll, Set<String> updated, Set<String> previousSelected) throws Exception {
        DefaultModuleDescriptor descriptor = (DefaultModuleDescriptor)XmlModuleDescriptorParser.getInstance()
            .parseDescriptor(settings, input.toURI().toURL(), true);
        if (descriptor.getInheritedDescriptors().length != 0)
            throw new IllegalArgumentException("Ivy extends descriptors are not supported yet");
        if (!updateAll && previousFile.isFile()) {
            DefaultModuleDescriptor previous = (DefaultModuleDescriptor)XmlModuleDescriptorParser.getInstance()
                .parseDescriptor(settings, previousFile.toURI().toURL(), true);
            Map<String, String> oldDeclarations = declarations(previous), current = declarations(descriptor);
            for (var rule : previous.getAllDependencyDescriptorMediators().getAllRules().entrySet()) {
                if (!(rule.getValue() instanceof OverrideDependencyDescriptorMediator)) continue;
                OverrideDependencyDescriptorMediator mediator = (OverrideDependencyDescriptorMediator)rule.getValue();
                Map<String, String> attributes = rule.getKey().getAttributes();
                String org = attributes.get("organisation"), module = attributes.get("module");
                String id = org + ":" + module;
                if (!previousSelected.contains(id) || !"exact".equals(rule.getKey().getPatternMatcher().getName()) || updated.contains(id)) continue;
                if (current.containsKey(id) && !Objects.equals(current.get(id), oldDeclarations.get(id))) continue;
                descriptor.addDependencyDescriptorMediator(ModuleId.newInstance(org, module), ExactPatternMatcher.INSTANCE, mediator);
            }
        }
        return descriptor;
    }
    static void writePinned(DefaultModuleDescriptor descriptor, File destination) throws Exception {
        XmlModuleDescriptorWriter.write(descriptor, destination);
        Document document = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(destination);
        NodeList dependencies = document.getElementsByTagName("dependency");
        for (int index = 0; index < dependencies.getLength(); index++) {
            Element dependency = (Element)dependencies.item(index);
            // Ivy applies descriptor overrides to transitive edges only. Pin root edges
            // explicitly too, retaining the native dynamic constraint for future updates.
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
        Transformer transformer = TransformerFactory.newInstance().newTransformer();
        transformer.setOutputProperty(OutputKeys.INDENT, "yes");
        transformer.transform(new DOMSource(document), new StreamResult(destination));
    }
    private static void exportPomMetadata(IvySettings settings, Document document, Element result) throws Exception {
        Element metadata = element(document, result, "metadata");
        Set<String> seen = new HashSet<>();
        for (RepositoryCacheManager manager : settings.getRepositoryCacheManagers()) {
            if (!(manager instanceof DefaultRepositoryCacheManager)) continue;
            DefaultRepositoryCacheManager cache = (DefaultRepositoryCacheManager)manager;
            List<Path> originals;
            try (var paths = Files.walk(cache.getBasedir().toPath())) {
                originals = paths.filter(path -> path.toString().endsWith(".xml.original"))
                    .sorted().collect(java.util.stream.Collectors.toList());
            }
            for (Path original : originals) {
                DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
                factory.setNamespaceAware(true);
                factory.setFeature("http://xml.org/sax/features/external-general-entities", false);
                factory.setFeature("http://xml.org/sax/features/external-parameter-entities", false);
                factory.setFeature("http://apache.org/xml/features/nonvalidating/load-external-dtd", false);
                Document raw = factory.newDocumentBuilder().parse(original.toFile());
                if (!"project".equals(raw.getDocumentElement().getLocalName())) continue;
                Path normalized = Path.of(original.toString().substring(0, original.toString().length() - ".original".length()));
                ModuleDescriptor descriptor = XmlModuleDescriptorParser.getInstance().parseDescriptor(settings, normalized.toUri().toURL(), false);
                ModuleRevisionId id = descriptor.getModuleRevisionId();
                if (!seen.add(id.toString())) continue;
                ArtifactOrigin origin = cache.getSavedArtifactOrigin(DefaultArtifact.newIvyArtifact(id, descriptor.getResolvedPublicationDate()));
                if (origin == null || ArtifactOrigin.isUnknown(origin)) throw new IOException("Missing native metadata origin for " + id);
                element(document, metadata, "pom", "group", component(id.getOrganisation()), "name", component(id.getName()),
                    "version", component(id.getRevision()), "file", original.toString(), "url", origin.getLocation());
            }
        }
    }
    static void exportNative(IvySettings settings, File input, Path output, ResolveReport report) throws Exception {
        // Canonicalize generated XML only after the native project target has finished.
        Locale.setDefault(Locale.ROOT);
        if (report.hasError()) throw new IOException(report.getAllProblemMessages().toString());
        Document document = DocumentBuilderFactory.newInstance().newDocumentBuilder().newDocument();
        Element result = document.createElement("resolution"); document.appendChild(result);
        Element modules = element(document, result, "modules"), artifacts = element(document, result, "artifacts");
        TreeMap<String, IvyNode> selected = new TreeMap<>();
        for (IvyNode node : report.getDependencies()) {
            if (node.isCompletelyEvicted() || node.getModuleRevision() == null) continue;
            ModuleRevisionId id = node.getResolvedId();
            if (id.getBranch() != null) throw new IllegalArgumentException("Ivy branches are not supported yet");
            String key = key(id.getModuleId());
            IvyNode existing = selected.putIfAbsent(key, node);
            if (existing != null && !existing.getResolvedId().equals(id))
                throw new IllegalArgumentException("Multiple selected revisions of " + key + " are not supported yet");
        }
        // Reparse the declaration so pins for no-longer-selected modules do not enter the new lock.
        DefaultModuleDescriptor descriptor = (DefaultModuleDescriptor)XmlModuleDescriptorParser.getInstance()
            .parseDescriptor(settings, input.toURI().toURL(), true);
        for (var entry : selected.entrySet()) {
            IvyNode node = entry.getValue(); ModuleRevisionId id = node.getResolvedId();
            String org = component(id.getOrganisation()), module = component(id.getName()), rev = component(id.getRevision());
            String location = org.replace('.', '/') + "/" + module + "/" + rev;
            Path file = output.resolve("modules").resolve(location).resolve("ivy.xml"); Files.createDirectories(file.getParent());
            ModuleDescriptor md = node.getModuleRevision().getDescriptor();
            if (md.getInheritedDescriptors().length != 0) throw new IllegalArgumentException("Ivy extends descriptors are not supported yet");
            XmlModuleDescriptorWriter.write(md, file.toFile());
            Element record = element(document, modules, "module", "group", org, "name", module, "version", rev, "path", location + "/ivy.xml", "file", file.toString());
            MetadataArtifactDownloadReport metadata = node.getModuleRevision().getReport();
            if (metadata != null && metadata.getArtifactOrigin() != null && metadata.getOriginalLocalFile() != null)
                element(document, record, "original", "url", metadata.getArtifactOrigin().getLocation(), "file", metadata.getOriginalLocalFile().toString());
            descriptor.addDependencyDescriptorMediator(id.getModuleId(), ExactPatternMatcher.INSTANCE, new OverrideDependencyDescriptorMediator(null, rev));
        }
        Map<String, ArtifactDownloadReport> downloads = new TreeMap<>();
        for (ArtifactDownloadReport download : report.getAllArtifactsReports())
            downloads.put(download.getArtifact().getId().toString(), download);
        Ivy sourceIvy = Ivy.newInstance(settings);
        sourceIvy.pushContext();
        try {
            for (IvyNode node : selected.values()) {
                List<Artifact> sources = new ArrayList<>();
                for (Artifact artifact : node.getModuleRevision().getDescriptor().getAllArtifacts())
                    if ("sources".equals(artifact.getExtraAttribute("classifier")) ||
                        Set.of("source", "sources", "src").contains(artifact.getType()))
                        if (!downloads.containsKey(artifact.getId().toString()) && artifact.getUrl() == null) sources.add(artifact);
                if (sources.isEmpty()) continue;
                DownloadOptions options = new DownloadOptions(); options.setLog("quiet");
                DownloadReport available = node.getModuleRevision().getArtifactResolver().download(sources.toArray(new Artifact[0]), options);
                for (ArtifactDownloadReport source : available.getArtifactsReports())
                    if (source.getDownloadStatus() != DownloadStatus.FAILED && source.getLocalFile() != null)
                        downloads.put(source.getArtifact().getId().toString(), source);
            }
        } finally { sourceIvy.popContext(); }
        for (ArtifactDownloadReport download : downloads.values()) {
            Artifact artifact = download.getArtifact(); ModuleRevisionId id = artifact.getModuleRevisionId();
            if (artifact.getUrl() != null) throw new IllegalArgumentException("Explicit Ivy artifact URLs are not supported yet");
            if (!selected.containsKey(key(id.getModuleId()))) continue;
            String classifier = artifact.getExtraAttribute("classifier");
            if (classifier == null) classifier = ""; else component(classifier);
            String org = component(id.getOrganisation()), module = component(id.getName()), rev = component(id.getRevision());
            String name = component(artifact.getName()), ext = component(artifact.getExt());
            String path = org.replace('.', '/') + "/" + module + "/" + rev + "/" + name + "-" + rev + (classifier.isEmpty() ? "" : "-" + classifier) + "." + ext;
            if (download.getLocalFile() == null || download.getArtifactOrigin() == null) throw new IOException("Missing native artifact origin for " + artifact);
            element(document, artifacts, "artifact", "group", org, "module", module, "version", rev, "name", name,
                "ext", ext, "type", artifact.getType(), "classifier", classifier, "path", path,
                "url", download.getArtifactOrigin().getLocation(), "file", download.getLocalFile().toString());
        }
        // The generated lock has a stable publication date; original dependency metadata stays intact.
        descriptor.setResolvedPublicationDate(org.apache.ivy.util.DateUtil.parse("19700101000001"));
        if (descriptor.getModuleRevisionId().getRevision().startsWith("working@")) {
            ModuleRevisionId id = descriptor.getModuleRevisionId();
            ModuleRevisionId stable = ModuleRevisionId.newInstance(id.getOrganisation(), id.getName(), "working");
            descriptor.setModuleRevisionId(stable); descriptor.setResolvedModuleRevisionId(stable);
        }
        writePinned(descriptor, output.resolve("ivy.lock.xml").toFile());
        exportPomMetadata(settings, document, result);
        Transformer transformer = TransformerFactory.newInstance().newTransformer();
        transformer.setOutputProperty(OutputKeys.INDENT, "yes");
        transformer.transform(new DOMSource(document), new StreamResult(output.resolve("resolution.xml").toFile()));
    }
    public static void main(String[] args) throws Exception {
        File input = new File(args[0]), settingsFile = new File(args[1]);
        Path output = Path.of(args[2]); Files.createDirectories(output);
        IvySettings settings = new IvySettings();
        settings.setDefaultCache(output.resolve("cache").toFile());
        if (settingsFile.isFile()) settings.load(settingsFile); else settings.loadDefault();
        isolate(settings, output);
        boolean updateAll = args[4].equals("all");
        Set<String> updated = new HashSet<>(Arrays.asList(args[5].split(",")));
        Set<String> previousSelected = args.length > 6 ? new HashSet<>(Arrays.asList(args[6].split(","))) : Set.of();
        DefaultModuleDescriptor descriptor = pinned(settings, input, new File(args[3]), updateAll, updated, previousSelected);
        Ivy ivy = Ivy.newInstance(settings);
        ResolveReport report = ivy.resolve(descriptor, new ResolveOptions().setConfs(new String[]{"*"}).setRefresh(updateAll || !updated.equals(Set.of(""))));
        exportNative(settings, input, output, report);
    }
}
