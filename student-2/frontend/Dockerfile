FROM maven:3.9.11-eclipse-temurin-21-alpine AS build
WORKDIR /workspace
COPY pom.xml ./
COPY database-api/pom.xml database-api/pom.xml
COPY backend/pom.xml backend/pom.xml
COPY frontend/pom.xml frontend/pom.xml
COPY frontend/src frontend/src
RUN mvn -pl frontend -am package -DskipTests

FROM eclipse-temurin:21-jre-alpine
RUN apk add --no-cache curl
WORKDIR /app
COPY --from=build /workspace/frontend/target/frontend-*.jar app.jar
EXPOSE 5201
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
