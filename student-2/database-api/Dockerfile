FROM maven:3.9.11-eclipse-temurin-21-alpine AS build
WORKDIR /workspace
COPY pom.xml ./
COPY database-api/pom.xml database-api/pom.xml
COPY backend/pom.xml backend/pom.xml
COPY frontend/pom.xml frontend/pom.xml
COPY database-api/src database-api/src
RUN mvn -pl database-api -am package -DskipTests

FROM eclipse-temurin:21-jre-alpine
RUN apk add --no-cache curl
WORKDIR /app
COPY --from=build /workspace/database-api/target/database-api-*.jar app.jar
EXPOSE 9002
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
