using System;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;

internal static class WindowsMediaInspect {
    static readonly Regex Active = new Regex("<!doctype|<!entity|<script|javascript:|https?://|onload\\s*=|onerror\\s*=|<foreignobject",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    static readonly Regex SvgOpen = new Regex("<svg(?![A-Za-z0-9_])", RegexOptions.IgnoreCase);
    static readonly Regex ViewBox = new Regex("(?<![A-Za-z0-9_])viewBox\\s*=\\s*[\"']\\s*[\\d.+-]+\\s+[\\d.+-]+\\s+([\\d.]+)\\s+([\\d.]+)\\s*[\"']",
        RegexOptions.IgnoreCase);
    static readonly Regex Width = new Regex("(?<![A-Za-z0-9_])width\\s*=\\s*[\"']([\\d.]+)", RegexOptions.IgnoreCase);
    static readonly Regex Height = new Regex("(?<![A-Za-z0-9_])height\\s*=\\s*[\"']([\\d.]+)", RegexOptions.IgnoreCase);

    static ushort U16(byte[] data, int at) { return (ushort)((data[at] << 8) | data[at + 1]); }
    static uint U32(byte[] data, int at) {
        return ((uint)data[at] << 24) | ((uint)data[at + 1] << 16) | ((uint)data[at + 2] << 8) | data[at + 3];
    }
    static bool FontMagic(byte[] data) {
        if (data.Length < 4) return false;
        string tag = Encoding.ASCII.GetString(data, 0, 4);
        return tag == "OTTO" || tag == "true" || (data[0] == 0 && data[1] == 1 && data[2] == 0 && data[3] == 0);
    }
    static string Font(byte[] head, long size) {
        int tables = head.Length >= 6 ? U16(head, 4) : 0;
        if (tables < 1 || tables > 128 || 12 + tables * 16 > head.Length) return "{\"rejected\":\"FONT_TABLE_LIMIT\"}";
        for (int index = 0; index < tables; index++) {
            int at = 12 + index * 16 + 8; ulong end = (ulong)U32(head, at) + U32(head, at + 4);
            if (end > (ulong)size) return "{\"rejected\":\"FONT_TABLE_RANGE\"}";
        }
        return Special("font", size, 0, 0, 0, 0);
    }
    static double Number(Match match, int group) {
        double result; return match.Success && double.TryParse(match.Groups[group].Value,
            NumberStyles.Float, CultureInfo.InvariantCulture, out result) ? result : 0;
    }
    static string Num(double value) { return value.ToString("0.################", CultureInfo.InvariantCulture); }
    static string Special(string kind, long size, double width, double height, int video, int frames) {
        return "{\"special\":{\"mediaKind\":\"" + kind + "\",\"durationSeconds\":0,\"sizeBytes\":" + size +
            ",\"width\":" + Num(width) + ",\"height\":" + Num(height) + ",\"videoStreams\":" + video +
            ",\"audioStreams\":0,\"streamCount\":1,\"declaredFrames\":" + frames + "}}";
    }
    static string Svg(string text, long size, double maxWidth, double maxHeight) {
        if (size > 16 * 1024 * 1024) return "{\"rejected\":\"SVG_SIZE_LIMIT\"}";
        string remote = text.Replace("http://www.w3.org/2000/svg", "").Replace("http://www.w3.org/1999/xlink", "");
        Match open = SvgOpen.Match(text);
        if (!open.Success || Active.IsMatch(remote)) return "{\"rejected\":\"SVG_ACTIVE_CONTENT\"}";
        int end = text.IndexOf('>', open.Index); string tag = end >= 0 ? text.Substring(open.Index, end - open.Index + 1) : "";
        Match view = ViewBox.Match(tag), widthMatch = Width.Match(tag), heightMatch = Height.Match(tag);
        double width = widthMatch.Success ? Number(widthMatch, 1) : Number(view, 1);
        double height = heightMatch.Success ? Number(heightMatch, 1) : Number(view, 2);
        if (!(width > 0 && height > 0) || width > maxWidth || height > maxHeight)
            return "{\"rejected\":\"DIMENSION_LIMIT\"}";
        return Special("svg", size, width, height, 1, 1);
    }
    static string Inspect(string path, long maxBytes, double maxWidth, double maxHeight) {
        long size = new FileInfo(path).Length;
        if (size <= 0 || size > maxBytes) return "{\"rejected\":\"SIZE_LIMIT\"}";
        int count = (int)Math.Min(65536, size); byte[] head = new byte[count];
        using (FileStream stream = File.OpenRead(path)) stream.Read(head, 0, count);
        if (FontMagic(head)) return Font(head, size);
        string prefix = Encoding.UTF8.GetString(head).TrimStart().ToLowerInvariant();
        if (prefix.StartsWith("<svg") || prefix.StartsWith("<?xml")) {
            if (size > 16 * 1024 * 1024) return "{\"rejected\":\"SVG_SIZE_LIMIT\"}";
            string text = File.ReadAllText(path, Encoding.UTF8);
            return Svg(text, size, maxWidth, maxHeight);
        }
        return "{\"special\":null}";
    }
    public static int Main(string[] args) {
        try {
            if (args.Length != 4) throw new ArgumentException("usage: inspect INPUT MAX_BYTES MAX_WIDTH MAX_HEIGHT");
            Console.WriteLine(Inspect(args[0], long.Parse(args[1]), double.Parse(args[2], CultureInfo.InvariantCulture),
                double.Parse(args[3], CultureInfo.InvariantCulture))); return 0;
        } catch (Exception error) { Console.Error.WriteLine("native-media-inspect: " + error.Message); return 70; }
    }
}
