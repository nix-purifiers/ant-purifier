// SPDX-License-Identifier: MIT
package org.nixpurifiers.ant.legacy;
import java.io.File;

/** Validate the already-selected runtime without executing project tasks. */
public final class Check {
    public static void main(String[] args) throws Exception {
        Guard.validate(new File(System.getProperty("user.dir")));
    }
}
