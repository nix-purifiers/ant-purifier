// SPDX-License-Identifier: MIT
package org.nixpurifiers.ant;

import java.io.*;
import java.nio.file.*;
import java.util.*;
import org.apache.ivy.core.module.descriptor.*;
import org.apache.ivy.core.module.id.ModuleId;
import org.apache.ivy.core.settings.IvySettings;
import org.apache.ivy.plugins.matcher.ExactPatternMatcher;
import org.apache.ivy.plugins.resolver.*;

/** Nix-selected coordinates and repositories, separate from download locks. */
final class ProjectInputs {
    private static Properties properties() throws IOException {
        Properties result = new Properties();
        String path = System.getenv("ANT_PURIFIER_INPUT_PROPERTIES");
        if (path != null) try (Reader input = Files.newBufferedReader(Path.of(path))) { result.load(input); }
        return result;
    }
    static void configure(IvySettings settings) throws IOException {
        Properties properties = properties();
        if (properties.isEmpty() || "nix-purifier-project-inputs".equals(settings.getDefaultResolver().getName())) return;
        ChainResolver chain = new ChainResolver();
        chain.setName("nix-purifier-project-inputs"); chain.setReturnFirst(true); chain.setSettings(settings);
        int index = 0;
        while (properties.containsKey("repository." + index)) {
            IBiblioResolver resolver = new IBiblioResolver();
            resolver.setName("nix-project-input-" + index);
            resolver.setM2compatible(true); resolver.setUsepoms(true);
            resolver.setRoot(properties.getProperty("repository." + index++));
            resolver.setSettings(settings); chain.add(resolver);
        }
        chain.add(settings.getDefaultResolver());
        settings.addResolver(chain); settings.setDefaultResolver(chain.getName());
    }
    static void select(DefaultModuleDescriptor descriptor) throws IOException {
        Properties properties = properties();
        for (String key : properties.stringPropertyNames()) {
            if (!key.startsWith("module.")) continue;
            String[] coordinate = key.substring(7).split(":", 2);
            if (coordinate.length != 2) throw new IOException("Invalid Nix module coordinate: " + key);
            descriptor.addDependencyDescriptorMediator(ModuleId.newInstance(coordinate[0], coordinate[1]),
                ExactPatternMatcher.INSTANCE, new OverrideDependencyDescriptorMediator(null, properties.getProperty(key)));
        }
    }
}
