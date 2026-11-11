import Foundation
import MapKit

@main
struct Geocode {
    static func main() async {
        do {
            let request = MKLocalSearch.Request()
            request.naturalLanguageQuery = CommandLine.arguments[1]
            let response = try await MKLocalSearch(request: request).start()
            guard let result = response.mapItems.first else {
                throw CocoaError(.fileReadUnknown)
            }
            let point = result.location.coordinate
            let value: [String: Any] = [
                "name": result.address?.fullAddress ?? result.name ?? CommandLine.arguments[1],
                "lat": point.latitude,
                "lon": point.longitude,
            ]
            let json = try JSONSerialization.data(withJSONObject: value)
            print(String(decoding: json, as: UTF8.self))
        } catch {
            FileHandle.standardError.write(Data("\(error)\n".utf8))
            exit(1)
        }
    }
}
