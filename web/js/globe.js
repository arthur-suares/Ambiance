import * as THREE from "three";

const host = document.querySelector("#globe-scene");
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

if (host) {
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 100);
    camera.position.set(0, 0, 7.5);

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.7));
    renderer.setSize(host.clientWidth, host.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(renderer.domElement);

    const globe = new THREE.Group();
    globe.position.set(0, -1.1, 0);
    scene.add(globe);

    const earthRadius = 2.85;
    const geometry = new THREE.SphereGeometry(earthRadius, 88, 64);
    const material = new THREE.MeshStandardMaterial({
        color: 0xffffff,
        emissive: 0x141e27,
        emissiveIntensity: 0.55,
        roughness: 1,
        metalness: 0,
    });
    const planetaryPalette = {
        oceanDeep: new THREE.Color("#24445E"),
        ocean: new THREE.Color("#2E4A63"),
        ice: new THREE.Color("#839AAB"),
        land: new THREE.Color("#6C7878"),
        night: new THREE.Color("#101918"),
    };
    material.onBeforeCompile = (shader) => {
        shader.uniforms.uOceanDeep = { value: planetaryPalette.oceanDeep };
        shader.uniforms.uOcean = { value: planetaryPalette.ocean };
        shader.uniforms.uIce = { value: planetaryPalette.ice };
        shader.uniforms.uLand = { value: planetaryPalette.land };
        shader.uniforms.uNight = { value: planetaryPalette.night };

        shader.vertexShader = shader.vertexShader.replace(
            "#include <common>",
            "#include <common>\nvarying vec3 vEarthWorldNormal;",
        );
        shader.vertexShader = shader.vertexShader.replace(
            "#include <defaultnormal_vertex>",
            "#include <defaultnormal_vertex>\nvEarthWorldNormal = normalize(mat3(modelMatrix) * objectNormal);",
        );
        shader.fragmentShader = shader.fragmentShader.replace(
            "#include <common>",
            `#include <common>
            uniform vec3 uOceanDeep;
            uniform vec3 uOcean;
            uniform vec3 uIce;
            uniform vec3 uLand;
            uniform vec3 uNight;
            varying vec3 vEarthWorldNormal;`,
        );
        shader.fragmentShader = shader.fragmentShader.replace(
            "#include <map_fragment>",
            `#include <map_fragment>
            vec3 sourceColor = diffuseColor.rgb;
            float sourceLuminance = dot(sourceColor, vec3(0.299, 0.587, 0.114));
            float oceanMask = smoothstep(0.008, 0.032, sourceColor.b - sourceColor.g);
            float landIce = smoothstep(0.26, 0.65, sourceLuminance) * (1.0 - oceanMask);
            float detail = mix(0.58, 1.5, smoothstep(0.02, 0.32, sourceLuminance));
            vec3 landColor = mix(uLand, uIce, landIce * 0.45);
            float oceanBlend = 0.62 + smoothstep(0.03, 0.26, sourceLuminance) * 0.16;
            vec3 oceanColor = mix(uOceanDeep, uOcean, oceanBlend);
            vec3 dayColor = mix(landColor, oceanColor, oceanMask) * detail;
            float dayLuminance = dot(dayColor, vec3(0.299, 0.587, 0.114));
            dayColor = mix(vec3(dayLuminance), dayColor, 1.32);
            float sunlight = max(dot(normalize(vEarthWorldNormal), normalize(vec3(-4.0, 3.0, 5.0))), 0.0);
            float dayMask = smoothstep(0.015, 0.42, sunlight);
            vec3 nightColor = mix(uNight, uOceanDeep, oceanMask * 0.28);
            diffuseColor.rgb = mix(nightColor, dayColor, dayMask);`,
        );
    };
    material.customProgramCacheKey = () => "earth-biome-palette-v4";
    const earth = new THREE.Mesh(geometry, material);
    earth.rotation.z = -0.13;
    globe.add(earth);

    const cityMaterial = new THREE.MeshBasicMaterial({
        map: new THREE.DataTexture(new Uint8Array([0, 0, 0, 0]), 1, 1, THREE.RGBAFormat),
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
    });
    cityMaterial.map.needsUpdate = true;
    cityMaterial.onBeforeCompile = (shader) => {
        shader.vertexShader = shader.vertexShader.replace(
            "#include <common>",
            "#include <common>\nvarying vec3 vEarthWorldNormal;",
        );
        shader.vertexShader = shader.vertexShader.replace(
            "#include <defaultnormal_vertex>",
            "#include <defaultnormal_vertex>\nvEarthWorldNormal = normalize(mat3(modelMatrix) * objectNormal);",
        );
        shader.fragmentShader = shader.fragmentShader.replace(
            "#include <common>",
            "#include <common>\nvarying vec3 vEarthWorldNormal;",
        );
        shader.fragmentShader = shader.fragmentShader.replace(
            "#include <map_fragment>",
            `#include <map_fragment>
            float citySignal = texture2D(map, vMapUv).r;
            float daylight = max(dot(normalize(vEarthWorldNormal), normalize(vec3(-4.0, 3.0, 5.0))), 0.0);
            float nightSide = 1.0 - smoothstep(0.0, 0.28, daylight);
            diffuseColor.rgb = vec3(1.0, 0.65, 0.32);
            diffuseColor.a *= smoothstep(0.025, 0.2, citySignal) * nightSide;`,
        );
    };
    cityMaterial.customProgramCacheKey = () => "earth-city-lights-night-side-v1";

    const cityLights = new THREE.Mesh(
        new THREE.SphereGeometry(earthRadius + 0.012, 88, 64),
        cityMaterial,
    );
    globe.add(cityLights);

    const cloudsMaterial = new THREE.MeshStandardMaterial({
        color: 0xf2f7fa,
        transparent: true,
        opacity: 0.38,
        depthWrite: false,
        roughness: 1,
    });
    const clouds = new THREE.Mesh(
        new THREE.SphereGeometry(earthRadius + 0.02, 88, 64),
        cloudsMaterial,
    );
    globe.add(clouds);

    scene.add(new THREE.HemisphereLight(0xd8ead8, 0x14231b, 1.8));
    scene.add(new THREE.AmbientLight(0xc4e4cd, 0.8));
    const sunlight = new THREE.DirectionalLight(0xeaf3df, 2.6);
    sunlight.position.set(-4, 3, 5);
    scene.add(sunlight);

    function makeFallbackMap() {
        const canvas = document.createElement("canvas");
        canvas.width = 2048;
        canvas.height = 1024;
        const context = canvas.getContext("2d");
        context.fillStyle = "#12392e";
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.fillStyle = "#83ae79";
        const land = [
            [[.08,.25],[.13,.14],[.2,.12],[.24,.19],[.3,.22],[.28,.32],[.23,.37],[.21,.48],[.16,.52],[.12,.42]],
            [[.25,.51],[.3,.48],[.33,.58],[.32,.72],[.29,.87],[.26,.78],[.24,.64]],
            [[.43,.23],[.48,.2],[.5,.25],[.48,.31],[.44,.29]],
            [[.45,.32],[.53,.29],[.57,.35],[.55,.47],[.52,.59],[.49,.72],[.45,.62],[.43,.48]],
            [[.52,.23],[.61,.17],[.72,.18],[.79,.25],[.88,.27],[.91,.37],[.85,.43],[.78,.41],[.75,.48],[.68,.44],[.64,.36],[.57,.39]],
            [[.77,.57],[.84,.56],[.87,.63],[.84,.7],[.78,.68]],
            [[.12,.1],[.17,.06],[.21,.08],[.2,.14],[.15,.16]],
        ];
        for (const shape of land) {
            context.beginPath();
            context.moveTo(shape[0][0] * canvas.width, shape[0][1] * canvas.height);
            for (const [x, y] of shape.slice(1)) context.lineTo(x * canvas.width, y * canvas.height);
            context.closePath();
            context.fill();
        }
        const texture = new THREE.CanvasTexture(canvas);
        texture.colorSpace = THREE.SRGBColorSpace;
        material.map = texture;
        material.color.set(0xffffff);
        material.needsUpdate = true;
    }

    const textureLoader = new THREE.TextureLoader();
    textureLoader.load(
        "https://threejs.org/examples/textures/planets/earth_atmos_2048.jpg",
        (texture) => {
            texture.colorSpace = THREE.SRGBColorSpace;
            material.map = texture;
            material.needsUpdate = true;
        },
        undefined,
        makeFallbackMap,
    );

    textureLoader.load(
        "https://threejs.org/examples/textures/planets/earth_lights_2048.png",
        (texture) => {
            texture.colorSpace = THREE.SRGBColorSpace;
            cityMaterial.map = texture;
            cityMaterial.needsUpdate = true;
        },
    );

    textureLoader.load(
        "https://threejs.org/examples/textures/planets/earth_clouds_1024.png",
        (texture) => {
            texture.colorSpace = THREE.SRGBColorSpace;
            cloudsMaterial.map = texture;
            cloudsMaterial.needsUpdate = true;
        },
        undefined,
        () => {
            const canvas = document.createElement("canvas");
            canvas.width = 1024;
            canvas.height = 512;
            const context = canvas.getContext("2d");
            let seed = 41;
            const random = () => {
                seed = (seed * 16807) % 2147483647;
                return (seed - 1) / 2147483646;
            };
            for (let index = 0; index < 180; index++) {
                const x = random() * canvas.width;
                const y = random() * canvas.height;
                const radius = 8 + random() * 36;
                context.fillStyle = `rgba(228, 239, 244, ${0.025 + random() * 0.06})`;
                context.beginPath();
                context.ellipse(x, y, radius * 1.8, radius * 0.6, random() * Math.PI, 0, Math.PI * 2);
                context.fill();
            }
            const fallbackClouds = new THREE.CanvasTexture(canvas);
            fallbackClouds.colorSpace = THREE.SRGBColorSpace;
            cloudsMaterial.map = fallbackClouds;
            cloudsMaterial.needsUpdate = true;
        },
    );

    const resize = () => {
        const width = host.clientWidth;
        const height = host.clientHeight;
        if (!width || !height) return;
        camera.aspect = width / height;
        camera.fov = camera.aspect < 0.8 ? 64 : 34;
        camera.updateProjectionMatrix();
        renderer.setSize(width, height);
    };
    const resizeObserver = new ResizeObserver(resize);
    resize();
    resizeObserver.observe(host);
    window.addEventListener("resize", resize);
    window.addEventListener("beforeunload", () => resizeObserver.disconnect(), { once: true });

    const animate = () => {
        if (!reducedMotion) {
            globe.rotation.y += 0.00035;
            clouds.rotation.y += 0.00065;
        }
        renderer.render(scene, camera);
        if (!reducedMotion) requestAnimationFrame(animate);
    };
    animate();
}