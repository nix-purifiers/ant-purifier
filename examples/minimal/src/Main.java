import org.apache.commons.lang3.StringUtils;

public final class Main {
    public static String greeting() { return StringUtils.capitalize("locked dependencies"); }
    public static void main(String[] arguments) {
        if (!greeting().equals("Locked dependencies")) throw new AssertionError(greeting());
        System.out.println(greeting());
    }
}
