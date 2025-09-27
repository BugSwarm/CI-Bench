import javalang

class JavaGlobalVariableVisitor:
    def __init__(self):
        # static variables
        self.global_assigns = {}
        
    def calculate_end_line(self, codes, start_line):
        lines = codes.splitlines()
        open_braces = 0
        close_braces = 0
        end_line = start_line
        for i in range(start_line - 1, len(lines)):
            line = lines[i]
            if line == "":
                continue
            open_braces = open_braces + line.count("(")
            close_braces = close_braces + line.count(")")
            if open_braces == close_braces and line[-1] == ';':
                end_line = i + 1
                break

        return end_line

    def visit(self, java_code):
        try:
            tree = javalang.parse.parse(java_code)
        except javalang.parser.JavaSyntaxError as e:
            print(f"[WARN] Java Syntax Error: {e}")
            return

        for path, node in tree.filter(javalang.tree.FieldDeclaration):
            if any(modifier == 'static' for modifier in node.modifiers):
                for d in node.declarators:
                    var_name = d.name
                    start_line = node.position.line
                    end_line = self.calculate_end_line(java_code, start_line)
                    self.global_assigns[var_name] = {
                        'start_line': start_line,
                        'end_line': end_line
                    }

    def get_global_variable(self):
        return self.global_assigns


def parse_global_var_from_java_code(file_content):
    visitor = JavaGlobalVariableVisitor()
    visitor.visit(file_content)
    return visitor.get_global_variable()


# Example Usage
if __name__ == "__main__":
    java_code = """
    public class Gl200ProtocolDecoder extends BaseProtocolDecoder {

    public Gl200ProtocolDecoder(Gl200Protocol protocol) {
        super(protocol);
    }

    private static final Pattern PATTERN_ACK = new PatternBuilder()
            .text("+ACK:GT")
            .expression("...,")                  // type
            .number("([0-9A-Z]{2}xxxx),")        // protocol version
            .number("(d{15}|x{14}),")            // imei
            .any().text(",")
            .number("(dddd)(dd)(dd)")            // date (yyyymmdd)
            .number("(dd)(dd)(dd),")             // time (hhmmss)
            .number("(xxxx)")                    // counter
            .text("$").optional()
            .compile();

    private static final Pattern PATTERN_INF = new PatternBuilder()
            .text("+").expression("(?:RESP|BUFF):GTINF,")
            .number("[0-9A-Z]{2}xxxx,")          // protocol version
            .number("(d{15}|x{14}),")            // imei
            .expression("(?:[0-9A-Z]{17},)?")    // vin
            .expression("(?:[^,]+)?,")           // device name
            .number("(xx),")                     // state
            .expression("(?:[0-9F]{20})?,")      // iccid
            .number("d{1,2},")
            .number("d{1,2},")
            .expression("[01],")                 // external power
            .number("([d.]+)?,")                 // odometer or external power
            .number("d*,")                       // backup battery or lightness
            .number("(d+.d+),")                  // battery
            .expression("([01]),")               // charging
            .number("(?:d),")                    // led
            .number("(?:d)?,")                   // gps on need
            .number("(?:d)?,")                   // gps antenna type
            .number("(?:d),").optional()         // gps antenna state
            .number("d{14},")                    // last fix time
            .groupBegin()
            .number("(d+),")                     // battery percentage
            .expression("[01]?,")                // flash type
            .number("(-?[d.]+)?,,,")             // temperature
            .or()
            .expression("(?:[01])?,").optional() // pin15 mode
            .number("(d+)?,")                    // adc1
            .number("(d+)?,").optional()         // adc2
            .number("(xx)?,")                    // digital input
            .number("(xx)?,")                    // digital output
            .number("[-+]dddd,")                 // timezone
            .expression("[01],")                 // daylight saving
            .groupEnd()
            .number("(dddd)(dd)(dd)")            // date (yyyymmdd)
            .number("(dd)(dd)(dd),")             // time (hhmmss)
            .number("(xxxx)")                    // counter
            .text("$").optional()
            .compile();

    private static final Pattern PATTERN_VER = new PatternBuilder()
            .text("+").expression("(?:RESP|BUFF):GTVER,")
            .number("[0-9A-Z]{2}xxxx,")          // protocol version
            .number("(d{15}|x{14}),")            // imei
            .expression("[^,]*,")                // device name
            .expression("([^,]*),")              // device type
            .number("(xxxx),")                   // firmware version
            .number("(xxxx),")                   // hardware version
            .number("(dddd)(dd)(dd)")            // date (yyyymmdd)
            .number("(dd)(dd)(dd),")             // time (hhmmss)
            .number("(xxxx)")                    // counter
            .text("$").optional()
            .compile();

    private static final Pattern PATTERN_LOCATION = new PatternBuilder()
            .number("(d{1,2})?,")                // hdop
            .number("(d{1,3}.d)?,")              // speed
            .number("(d{1,3})?,")                // course
            .number("(-?d{1,5}.d)?,")            // altitude
            .number("(-?d{1,3}.d{6})?,")         // longitude
            .number("(-?d{1,2}.d{6})?,")         // latitude
            .number("(dddd)(dd)(dd)")            // date (yyyymmdd)
            .number("(dd)(dd)(dd)").optional(2)  // time (hhmmss)
            .text(",")
            .groupBegin()
            .number("(0ddd)?,")                  // mcc
            .number("(0ddd)?,")                  // mnc
            .number("(xxxx)?,")                  // lac
            .number("(xxxx)?,")                  // cell
            .or()
            .number("(d+)?,")                    // mcc
            .number("(d+)?,")                    // mnc
            .number("(d+)?,")                    // lac
            .number("(d+)?,")                    // cell
            .groupEnd()
            .number("(?:d+|(d+.d))?,")           // odometer
            .compile();

    private static final Pattern PATTERN_OBD = new PatternBuilder()
            .text("+RESP:GTOBD,")
            .number("[0-9A-Z]{2}xxxx,")          // protocol version
            .number("(d{15}|x{14}),")            // imei
            .expression("(?:[0-9A-Z]{17})?,")    // vin
            .expression("[^,]{0,20},")           // device name
            .expression("[01],")                 // report type
            .number("x{1,8},")                   // report mask
            .expression("(?:[0-9A-Z]{17})?,")    // vin
            .number("[01],")                     // obd connect
            .number("(?:d{1,5})?,")              // obd voltage
            .number("(?:x{8})?,")                // support pids
            .number("(d{1,5})?,")                // engine rpm
            .number("(d{1,3})?,")                // speed
            .number("(-?d{1,3})?,")              // coolant temp
            .number("(d+.?d*|Inf|NaN)?,")        // fuel consumption
            .number("(d{1,5})?,")                // dtcs cleared distance
            .number("(?:d{1,5})?,")
            .expression("([01])?,")              // obd connect
            .number("(d{1,3})?,")                // number of dtcs
            .number("(x*),")                     // dtcs
            .number("(d{1,3})?,")                // throttle
            .number("(?:d{1,3})?,")              // engine load
            .number("(d{1,3})?,")                // fuel level
            .expression("(?:[0-9A],)?")          // obd protocol
            .number("(d+),")                     // odometer
            .expression(PATTERN_LOCATION.pattern())
            .number("(d{1,7}.d)?,")              // odometer
            .number("(dddd)(dd)(dd)")            // date (yyyymmdd)
            .number("(dd)(dd)(dd)").optional(2)  // time (hhmmss)
            .text(",")
            .number("(xxxx)")                    // count number
            .text("$").optional()
            .compile();

    private static final Pattern PATTERN_FRI = new PatternBuilder()
            .text("+").expression("(?:RESP|BUFF):GTFRI,")
            .number("(?:[0-9A-Z]{2}xxxx)?,")     // protocol version
            .number("(d{15}|x{14}),")            // imei
            .expression("(?:([0-9A-Z]{17}),)?")  // vin
            .expression("[^,]*,")                // device name
            .number("(d+)?,")                    // power
            .number("d{1,2},")                   // report type
            .number("d{1,2},")                   // count
            .expression("((?:")
            .expression(PATTERN_LOCATION.pattern())
            .expression(")+)")
            .groupBegin()
            .number("(d{1,7}.d)?,").optional()   // odometer
            .number("(d{1,3})?,")                // battery
            .or()
            .number("(d{1,7}.d)?,")              // odometer
            .number("(d{5}:dd:dd)?,")            // hour meter
            .number("(x+)?,")                    // adc 1
            .number("(x+)?,")                    // adc 2
            .number("(d{1,3})?,")                // battery
            .number("(?:(xx)(xx)(xx))?,")        // device status
            .number("(d+)?,")                    // rpm
            .number("(?:d+.?d*|Inf|NaN)?,")      // fuel consumption
            .number("(d+)?,")                    // fuel level
            .groupEnd()
            .number("(dddd)(dd)(dd)")            // date (yyyymmdd)
            .number("(dd)(dd)(dd)").optional(2)  // time (hhmmss)
            .text(",")
            .number("(xxxx)")                    // count number
            .text("$").optional()
            .compile();

    private static final Pattern PATTERN_IGN = new PatternBuilder()
            .text("+").expression("(?:RESP|BUFF):GTIG[NF],")
            .number("(?:[0-9A-Z]{2}xxxx)?,")     // protocol version
            .number("(d{15}|x{14}),")            // imei
            .expression("[^,]*,")                // device name
            .number("d+,")                       // ignition off duration
            .expression(PATTERN_LOCATION.pattern())
            .number("(d{5}:dd:dd)?,")            // hour meter
            .number("(d{1,7}.d)?,")              // odometer
            .number("(dddd)(dd)(dd)")            // date (yyyymmdd)
            .number("(dd)(dd)(dd)").optional(2)  // time (hhmmss)
            .text(",")
            .number("(xxxx)")                    // count number
            .text("$").optional()
            .compile();

    private static final Pattern PATTERN_IDA = new PatternBuilder()
            .text("+RESP:GTIDA,")
            .number("(?:[0-9A-Z]{2}xxxx)?,")     // protocol version
            .number("(d{15}|x{14}),")            // imei
            .expression("[^,]*,,")               // device name
            .number("([^,]+),")                  // rfid
            .expression("[01],")                 // report type
            .number("1,")                        // count
            .expression(PATTERN_LOCATION.pattern())
            .number("(d+.d),")                   // odometer
            .text(",,,,")
            .number("(dddd)(dd)(dd)")            // date (yyyymmdd)
            .number("(dd)(dd)(dd)").optional(2)  // time (hhmmss)
            .text(",")
            .number("(xxxx)")                    // count number
            .text("$").optional()
            .compile();

    private static final Pattern PATTERN_WIF = new PatternBuilder()
            .text("+RESP:GTWIF,")
            .number("(?:[0-9A-Z]{2}xxxx)?,")     // protocol version
            .number("(d{15}|x{14}),")            // imei
            .expression("[^,]*,")                // device name
            .number("(d+),")                     // count
            .number("((?:x{12},-?d+,,,,)+),,,,") // wifi
            .number("(d{1,3}),")                 // battery
            .number("(dddd)(dd)(dd)")            // date (yyyymmdd)
            .number("(dd)(dd)(dd)").optional(2)  // time (hhmmss)
            .text(",")
            .number("(xxxx)")                    // count number
            .text("$").optional()
            .compile();

    private static final Pattern PATTERN_GSM = new PatternBuilder()
            .text("+RESP:GTGSM,")
            .number("(?:[0-9A-Z]{2}xxxx)?,")     // protocol version
            .number("(d{15}|x{14}),")            // imei
            .expression("(?:STR|CTN|NMR|RTL),")  // fix type
            .expression("(.*)")                  // cells
            .number("(dddd)(dd)(dd)")            // date (yyyymmdd)
            .number("(dd)(dd)(dd)").optional(2)  // time (hhmmss)
            .text(",")
            .number("(xxxx)")                    // count number
            .text("$").optional()
            .compile();

    private static final Pattern PATTERN = new PatternBuilder()
            .text("+").expression("(?:RESP|BUFF):GT...,")
            .number("(?:[0-9A-Z]{2}xxxx)?,")     // protocol version
            .number("(d{15}|x{14}),")            // imei
            .expression("[^,]*,")                // device name
            .number("d*,")
            .number("(d{1,2}),")                 // report type
            .number("d{1,2},")                   // count
            .expression(PATTERN_LOCATION.pattern())
            .groupBegin()
            .number("(d{1,7}.d)?,").optional()   // odometer
            .number("(d{1,3})?,")                // battery
            .or()
            .number("(d{1,7}.d)?,")              // odometer
            .groupEnd()
            .number("(dddd)(dd)(dd)")            // date (yyyymmdd)
            .number("(dd)(dd)(dd)").optional(2)  // time (hhmmss)
            .text(",")
            .number("(xxxx)")                    // count number
            .text("$").optional()
            .compile();

    private static final Pattern PATTERN_BASIC = new PatternBuilder()
            .text("+").expression("(?:RESP|BUFF)").text(":")
            .expression("GT...,")
            .number("(?:[0-9A-Z]{2}xxxx)?,")     // protocol version
            .number("(d{15}|x{14}),")            // imei
            .any()
            .number("(d{1,2})?,")                // hdop
            .number("(d{1,3}.d)?,")              // speed
            .number("(d{1,3})?,")                // course
            .number("(-?d{1,5}.d)?,")            // altitude
            .number("(-?d{1,3}.d{6})?,")         // longitude
            .number("(-?d{1,2}.d{6})?,")         // latitude
            .number("(dddd)(dd)(dd)")            // date (yyyymmdd)
            .number("(dd)(dd)(dd)").optional(2)  // time (hhmmss)
            .text(",")
            .number("(0ddd),")                   // mcc
            .number("(0ddd),")                   // mnc
            .number("(xxxx),")                   // lac
            .number("(xxxx),").optional(4)       // cell
            .any()
            .number("(dddd)(dd)(dd)")            // date (yyyymmdd)
            .number("(dd)(dd)(dd)").optional(2)  // time (hhmmss)
            .text(",")
            .number("(xxxx)")                    // count number
            .text("$").optional()
            .compile();

    private Object decodeAck(Channel channel, SocketAddress remoteAddress, String sentence, String type) {
        Parser parser = new Parser(PATTERN_ACK, sentence);
        if (parser.matches()) {
            String protocolVersion = parser.next();
            DeviceSession deviceSession = getDeviceSession(channel, remoteAddress, parser.next());
            if (deviceSession == null) {
                return null;
            }
            if (type.equals("HBD")) {
                if (channel != null) {
                    parser.skip(6);
                    channel.write("+SACK:GTHBD," + protocolVersion + "," + parser.next() + "$", remoteAddress);
                }
            } else {
                Position position = new Position();
                position.setProtocol(getProtocolName());
                position.setDeviceId(deviceSession.getDeviceId());
                getLastLocation(position, parser.nextDateTime());
                position.setValid(false);
                position.set(Position.KEY_RESULT, "Command " + type + " accepted");
                return position;
            }
        }
        return null;
    }
    }
    """

    visitor = JavaGlobalVariableVisitor()
    visitor.visit(java_code)
    print(visitor.get_global_variable())