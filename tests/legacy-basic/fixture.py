# SPDX-License-Identifier: MIT
"""Original native Ant/Ivy inputs used by independent legacy controls."""
from pathlib import Path
import subprocess
import zipfile


def module(repository, sdk, name, version, source, dependencies=(), classpath=()):
    work = repository.parent/('compile-'+name+'-'+version)
    (work/'src/example').mkdir(parents=True)
    (work/'classes').mkdir()
    (work/'src/example'/('Shared.java' if name == 'shared' else 'Middle.java')).write_text(source)
    command = [str(Path(sdk)/'bin/javac'), '-d', str(work/'classes')]
    if classpath:
        command += ['-cp', ':'.join(map(str, classpath))]
    subprocess.run([*command, *map(str, (work/'src').rglob('*.java'))], check=True, capture_output=True)
    directory = repository/'example'/name/version
    directory.mkdir(parents=True)
    jar = directory/(name+'-'+version+'.jar')
    with zipfile.ZipFile(jar, 'w') as output:
        for file in sorted((work/'classes').rglob('*.class')):
            info = zipfile.ZipInfo(file.relative_to(work/'classes').as_posix(), (2000, 1, 1, 0, 0, 0))
            output.writestr(info, file.read_bytes())
    descriptor = '<ivy-module version="2.0"><info organisation="example" module="'+name+'" revision="'+version+'" status="release" publication="20000101000000"/><configurations><conf name="default"/></configurations><publications><artifact name="'+name+'" type="jar" ext="jar" conf="default"/></publications><dependencies>'
    for dependency, revision in dependencies:
        descriptor += '<dependency org="example" name="'+dependency+'" rev="'+revision+'" conf="default-&gt;default"/>'
    (directory/'ivy.xml').write_text(descriptor+'</dependencies></ivy-module>\n')
    return jar


def repository(root, context):
    root.mkdir()
    sdk = context['sdk']['home']
    one = module(root, sdk, 'shared', '1.0', 'package example; public class Shared { public static int value(){return 1;} }')
    two = module(root, sdk, 'shared', '2.0', 'package example; public class Shared { public static int value(){return 2;} }')
    middle = module(root, sdk, 'middle', '1.0', 'package example; public class Middle { public static int answer(){return Shared.value();} }', [('shared', '1.0')], [one])
    return {'shared1': one, 'shared2': two, 'middle': middle}


def project(root, url, context, revision='2.0'):
    root.mkdir()
    (root/'src/example').mkdir(parents=True)
    child = str(Path(context['manager']['runtimeHome'])/'bin/java')
    runtime_home = context['manager']['runtimeHome']
    (root/'src/example/Main.java').write_text('''package example;
import java.io.File;
public class Main {
  public static void main(String[] args) throws Exception {
    new File("test-started").createNewFile();
    if(Middle.answer()!=2 || Shared.value()!=2) throw new AssertionError("native conflict result");
    if(!System.getProperty("java.version").equals("1.6.0-119")) throw new AssertionError("native SDK version");
    if(!new File(System.getProperty("java.home")).getCanonicalPath().equals("'''+runtime_home+'''")) throw new AssertionError("native SDK home");
    if(!new File("/proc/self/exe").getCanonicalPath().equals(new File("'''+child+'''").getCanonicalPath())) throw new AssertionError("native SDK executable");
    System.out.println("LEGACY SDK6 CONFLICT AND JAVAEXEC PASSED");
  }
}
''')
    ivy = context['ivy']['output']
    (root/'build.xml').write_text('''<project name="legacy-proof" default="test" basedir=".">
  <property name="build.compiler" value="modern"/>
  <taskdef name="ivy-settings" classname="org.apache.ivy.ant.IvyConfigure" classpath="'''+ivy+'''"/>
  <taskdef name="ivy-resolve" classname="org.apache.ivy.ant.IvyResolve" classpath="'''+ivy+'''"/>
  <taskdef name="ivy-retrieve" classname="org.apache.ivy.ant.IvyRetrieve" classpath="'''+ivy+'''"/>
  <target name="settings"><ivy-settings file="ivysettings.xml"/></target>
  <target name="resolve" depends="settings"><ivy-resolve file="ivy.xml"/></target>
  <target name="retrieve" depends="resolve"><mkdir dir="build/deps"/><ivy-retrieve pattern="build/deps/[artifact]-[revision].[ext]"/></target>
  <target name="compile" depends="retrieve"><mkdir dir="build/classes"/><javac srcdir="src" destdir="build/classes"><classpath><fileset dir="build/deps" includes="*.jar"/></classpath></javac></target>
  <target name="test" depends="compile"><java classname="example.Main" fork="true" jvm="${java.home}/bin/java" failonerror="true"><classpath><pathelement location="build/classes"/><fileset dir="build/deps" includes="*.jar"/></classpath></java></target>
  <target name="unsupported-package" depends="compile"><jar jarfile="package-started.jar" basedir="build/classes"/></target>
</project>
''')
    (root/'ivysettings.xml').write_text('<ivysettings><settings defaultResolver="original"/><resolvers><url name="original"><ivy pattern="'+url+'/[organisation]/[module]/[revision]/ivy.xml"/><artifact pattern="'+url+'/[organisation]/[module]/[revision]/[artifact]-[revision].[ext]"/></url></resolvers></ivysettings>\n')
    (root/'ivy.xml').write_text('<ivy-module version="2.0"><info organisation="example" module="legacy-proof" revision="1" publication="20000101000000"/><dependencies><dependency org="example" name="middle" rev="1.0"/><dependency org="example" name="shared" rev="'+revision+'"/></dependencies></ivy-module>\n')
