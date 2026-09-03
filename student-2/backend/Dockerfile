FROM maven:3.9.11-eclipse-temurin-21-alpine AS build
WORKDIR /workspace
COPY pom.xml ./
COPY database-api/pom.xml database-api/pom.xml
COPY backend/pom.xml backend/pom.xml
COPY frontend/pom.xml frontend/pom.xml
COPY backend/src backend/src
RUN mvn -pl backend -am package -DskipTests

FROM eclipse-temurin:21-jre-alpine
RUN apk add --no-cache curl
WORKDIR /app
COPY --from=build /workspace/backend/target/backend-*.jar app.jar
EXPOSE 8002
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
