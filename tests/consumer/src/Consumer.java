public final class Consumer {
    public static void main(String[] arguments) {
        if (!Main.greeting().equals("Locked dependencies")) throw new AssertionError(Main.greeting());
    }
}
