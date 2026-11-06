// SPDX-License-Identifier: MIT
package org.nixpurifiers.ant.legacy;

import java.io.*;
import java.util.*;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.transform.*;
import javax.xml.transform.dom.DOMSource;
import javax.xml.transform.stream.StreamResult;
import org.w3c.dom.*;
import org.xml.sax.*;

final class IO {
    static void mkdir(File directory) throws IOException {
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Cannot create " + directory);
    }
    static String read(File file) throws IOException {
        Reader input = new InputStreamReader(new FileInputStream(file), "UTF-8");
        try {
            StringBuilder result = new StringBuilder(); char[] buffer = new char[8192]; int count;
            while ((count = input.read(buffer)) != -1) result.append(buffer, 0, count);
            return result.toString();
        } finally { input.close(); }
    }
    static void write(File file, String text) throws IOException {
        mkdir(file.getAbsoluteFile().getParentFile());
        Writer output = new OutputStreamWriter(new FileOutputStream(file), "UTF-8");
        try { output.write(text); } finally { output.close(); }
    }
    static Properties properties(File file) throws IOException {
        Reader reader = new InputStreamReader(new FileInputStream(file), "UTF-8");
        try { Properties result = new Properties(); result.load(reader); return result; }
        finally { reader.close(); }
    }
    static Document document() throws Exception {
        return DocumentBuilderFactory.newInstance().newDocumentBuilder().newDocument();
    }
    static Document parse(File file) throws Exception {
        String text = read(file);
        if (text.indexOf("<!DOCTYPE") >= 0 || text.indexOf("<!ENTITY") >= 0)
            throw new IOException("Generated legacy lock XML must not contain a document type or entity declaration");
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        javax.xml.parsers.DocumentBuilder builder = factory.newDocumentBuilder();
        builder.setEntityResolver(new EntityResolver() {
            public InputSource resolveEntity(String publicId, String systemId) throws SAXException {
                throw new SAXException("External generated legacy lock XML entities are unsupported");
            }
        });
        return builder.parse(new InputSource(new StringReader(text)));
    }
    static void xml(Document document, File file) throws Exception {
        mkdir(file.getAbsoluteFile().getParentFile());
        Transformer transformer = TransformerFactory.newInstance().newTransformer();
        transformer.setOutputProperty(OutputKeys.INDENT, "yes");
        transformer.setOutputProperty(OutputKeys.ENCODING, "UTF-8");
        transformer.transform(new DOMSource(document), new StreamResult(file));
    }
    static Element element(Document document, Element parent, String name, String... attributes) {
        Element result = document.createElement(name);
        for (int index = 0; index < attributes.length; index += 2)
            result.setAttribute(attributes[index], attributes[index + 1]);
        parent.appendChild(result); return result;
    }
    static String canonical(File file) throws IOException { return file.getCanonicalPath(); }
    static File temporaryDirectory() throws IOException {
        String directory = System.getenv("TMPDIR");
        File result = File.createTempFile("ant-legacy-", ".tmp", directory == null ? null : new File(directory));
        if (!result.delete() || !result.mkdir()) throw new IOException("Cannot prepare native Ivy cache");
        return result;
    }
    private static void delete(File file, String root, Set<String> visited) throws IOException {
        String canonical = file.getCanonicalPath();
        if (file.isDirectory() && (canonical.equals(root) || canonical.startsWith(root + File.separator)) && visited.add(canonical)) {
            File[] children = file.listFiles();
            if (children != null) for (File child : children) delete(child, root, visited);
        }
        file.delete();
    }
    static void delete(File file, String ownedRoot) {
        try { delete(file, ownedRoot, new HashSet<String>()); } catch (IOException ignored) { }
    }
}
